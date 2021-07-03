import json
import xxhash
from datetime import datetime
from flask import Flask, request
import requests
from requests.exceptions import Timeout, ConnectionError
import boto3
import jump

dynamodb = boto3.resource('dynamodb', region_name="us-east-1")
table = dynamodb.Table('LivingNodes')
cache = {}
app = Flask(__name__)
delay_period = 12 * 1000  # 12 seconds in milis
last = 0
ip_address = ""
live_nodes_pool_size = 1
live_nodes_list = []


def get_milis(dt):
    return int(round(dt.timestamp() * 1000))


@app.route('/health-check', methods=['GET', 'POST'])
def health_check():
    # update the DB that this server is still up by udating the lastAlive field
    timestamp = get_milis(datetime.now())
    item = {'ip': ip_address,
            'lastAlive': timestamp
            }
    table.put_item(Item=item)
    status_check()
    return f'it is I {ip_address} - at time {timestamp} im still alive'


def status_check():
    # check if the amount of servers has changed, if so repartition data
    current_live_nodes = get_live_node_list()
    current_num_nodes = len(current_live_nodes)
    if current_num_nodes != live_nodes_pool_size:
        repartition(current_num_nodes, current_live_nodes)


def repartition(current_num_nodes, nodes):
    # repartition the data for the buckets that require repartition
    global live_nodes_pool_size
    global live_nodes_list
    temp_dict = cache.copy()
    # iterate over each key to check if it require a repartition
    for v_key in temp_dict:
        new_node_index = jump.hash(int(v_key), current_num_nodes)
        old_node_index = jump.hash(int(v_key), live_nodes_pool_size)

        new_alt_node_index = (new_node_index + 1) % current_num_nodes
        old_alt_node_index = (old_node_index + 1) % live_nodes_pool_size
        try:
            node = nodes[new_node_index]
            alt_node = nodes[new_alt_node_index]
            old_node = live_nodes_list[old_node_index]
            old_alt_node = live_nodes_list[old_alt_node_index]
            # check if the node of this bucket has changed
            flag = node != old_node or alt_node != old_alt_node
        except:
            flag = True
        if flag:
            # for every key in the bucket send it to the new node and alt node
            bucket = cache.pop(v_key)
            for key in bucket:
                data, expiration_date = bucket[key]
                try:
                    put_data(key, data, expiration_date, v_key, node, alt_node)
                except:
                    continue
    # update the current node list and size
    live_nodes_pool_size = current_num_nodes
    live_nodes_list = nodes


def get_live_node_list():
    # query the db and returns a list of all the live nodes
    global live_nodes_list
    try:
        now = get_milis(datetime.now())
        response = table.scan()
        nodes = []
        for x in response['Items']:
            if int(x['lastAlive']) >= now - delay_period:
                nodes.append(x['ip'])
        nodes.sort()
        return nodes
    except:
        return None


def get_v_key(key):
    # hash the key to index
    return xxhash.xxh64_intdigest(key) % 1024


def get_nodes(key):
    # return a node (ip address) and alt node for each key
    try:
        nodes = get_live_node_list()
        v_key = get_v_key(key)
        index = jump.hash(v_key, len(nodes))
        node = nodes[index]
        alt_node = nodes[(index + 1) % len(nodes)]
        return v_key, node, alt_node
    except:
        return None


def get_url(node, key, op, v_key, data=None, expiration_date=None):
    # return a url for each action
    if op == 'put':
        return f'http://{node}:8080/{op}_internaly?v_key={v_key}&str_key={key}&data={data}' \
               f'&expiration_date={expiration_date}'
    else:
        return f'http://{node}:8080/{op}_internaly?str_key={key}&v_key={v_key}'


@app.route('/put', methods=['GET', 'POST'])
def put():
    # main put action - receives get requests from the ELB and navigate the item to the proper cache node
    try:
        key = request.args.get('str_key')
        data = request.args.get('data')
        expiration_date = request.args.get('expiration_date')
        v_key, node, alt_node = get_nodes(key)
    except Exception as e:
        return None
    try:
        ans = put_data(key, data, expiration_date, v_key, node, alt_node)
    except:
        return json.dumps({'item': data,
                           'key': key,
                           'Success': 'False'}), 404

    return ans, 200


def put_data(key, data, expiration_date, v_key, node, alt_node):
    # put the data in the proper cache node (internal or external)
    if node == ip_address:
        ans = json.loads(put_in_cache(v_key, key, data, expiration_date))
    else:
        ans = requests.post(get_url(node, key, 'put', v_key, data, expiration_date)).json()
    if alt_node == ip_address:
        json.loads(put_in_cache(v_key, key, data, expiration_date))
    else:
        requests.post(get_url(alt_node, key, 'put', v_key, data, expiration_date)).json()
    return ans


@app.route('/put_internaly', methods=['GET', 'POST'])
def put_internaly():
    # an outside request to put the data in the this machines cache
    v_key = int(request.args.get('v_key'))
    key = request.args.get('str_key')
    data = request.args.get('data')
    expiration_date = request.args.get('expiration_date')
    return put_in_cache(v_key, key, data, expiration_date)


def put_in_cache(v_key, key, data, expiration_date):
    # put the data in the this machines cache
    try:
        # actually setting the data
        bucket = cache.get(v_key)
        if not bucket:
            bucket = {}
        bucket[key] = (data, expiration_date)
        cache[v_key] = bucket
        return json.dumps({'item': cache[v_key][key],
                           'key': key,
                           'Success': 'True'})
    except:
        return "failed in put_internaly"


#  get items from nodes
@app.route('/get', methods=['GET', 'POST'])
def get():
    # main get action - receives get requests from the ELB and check the node and alt node for it
    key = request.args.get('str_key')
    v_key, node, alt_node = get_nodes(key)
    try:
        ans = requests.get(get_url(node, key, 'get', v_key), timeout=5)
        if ans.json().get('status code') == 404:
            ans = requests.get(get_url(alt_node, key, 'get', v_key), timeout=5)
    except (ConnectionError, Timeout):
        ans = requests.get(get_url(alt_node, key, 'get', v_key), timeout=5)
        if ans.json().get('status code') != 404:
            return ans.json(), 200
        else:
            return ans.json(), 404
    return ans.json().get('item'), 200


@app.route('/get_internaly', methods=['GET', 'POST'])
def get_internaly():
    # get the data in the this machines cache
    key = request.args.get('str_key')
    v_key = int(request.args.get('v_key'))
    # getting the data out of the cache
    try:
        item = cache[v_key][key]
        response = json.dumps({'status code': 200,
                               'item': item[0]})
    except:
        response = json.dumps({'status code': 404,
                               'item': "item does not exists"})
    return response

if __name__ == '__main__':
    ip_address = requests.get('https://api.ipify.org').text
    print('My public IP address is: {}'.format(ip_address))
    app.run(host='0.0.0.0', port=8080)
