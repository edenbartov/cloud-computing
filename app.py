import json
import xxhash
from datetime import datetime
from flask import Flask, request
import requests
from requests.exceptions import Timeout, ConnectionError
import boto3
import logging
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
    timestamp = get_milis(datetime.now())
    item = {'ip': ip_address,
            'lastAlive': timestamp
            }
    table.put_item(Item=item)
    status_check()
    return f'it is I {ip_address} - at time {timestamp} im still alive'


def status_check():
    current_live_nodes = get_live_node_list()
    current_num_nodes = len(current_live_nodes)
    if current_num_nodes != live_nodes_pool_size:
        repartition(current_num_nodes, current_live_nodes)


def repartition(current_num_nodes, nodes):
    global live_nodes_pool_size
    temp_dict = cache.copy()
    for v_key in temp_dict:
        new_node_index = jump.hash(int(v_key), current_num_nodes)
        old_node_index = jump.hash(int(v_key), live_nodes_pool_size)

        new_alt_node_index = (new_node_index + 1) % current_num_nodes
        old_alt_node_index = (old_node_index + 1) % live_nodes_pool_size

        # need to send all the data to the new node
        max_index = max([old_node_index, new_node_index, new_alt_node_index, old_alt_node_index])
        # if (max_index >= current_num_nodes or nodes[new_node_index] != nodes[old_node_index]) \
        #         or (nodes[new_alt_node_index] != nodes[old_alt_node_index]) or new_node_index != old_node_index:
        if True:
            bucket = cache.pop(v_key)
            node = nodes[new_node_index]
            alt_node = nodes[new_alt_node_index]
            for key in bucket:
                data, expiration_date = bucket[key]
                try:
                    put_data(key, data, expiration_date, v_key, node, alt_node)
                except:
                    continue

    live_nodes_pool_size = current_num_nodes


def get_live_node_list():
    global live_nodes_list
    try:
        app.logger.info('get_live_node_list')
        now = get_milis(datetime.now())
        response = table.scan()
        app.logger.info(f'get_live_node_list-  response: {response}')
        nodes = []
        for x in response['Items']:
            if int(x['lastAlive']) >= now - delay_period:
                nodes.append(x['ip'])
        nodes.sort()
        live_nodes_list = nodes
        return nodes
    except Exception as e:
        app.logger.info(f'error in get_live_node_list {e}')
        return None


def get_v_key(key):
    return xxhash.xxh64_intdigest(key) % 1024


def get_nodes(key):
    try:
        nodes = get_live_node_list()
        v_key = get_v_key(key)
        index = jump.hash(v_key, len(nodes))
        node = nodes[index]
        # alt_node = nodes[jump.hash((v_key + 1) % 1024, len(nodes))]
        alt_node = nodes[(index + 1) % len(nodes)]
        return v_key, node, alt_node
    except Exception as e:
        app.logger.info(f'failed in the get_nodes {e}')
        return None


def get_url(node, key, op, v_key, data=None, expiration_date=None):
    if op == 'put':
        return f'http://{node}:8080/{op}_internaly?v_key={v_key}&str_key={key}&data={data}' \
               f'&expiration_date={expiration_date}'
    else:
        return f'http://{node}:8080/{op}_internaly?str_key={key}&v_key={v_key}'


@app.route('/put', methods=['GET', 'POST'])
def put():
    try:
        key = request.args.get('str_key')
        data = request.args.get('data')
        expiration_date = request.args.get('expiration_date')
        v_key, node, alt_node = get_nodes(key)
    except Exception as e:
        app.logger.info(f'failed in the put when getting the arguments {e}')
        return None
    try:
        ans = put_data(key, data, expiration_date, v_key, node, alt_node)
    except:
        return json.dumps({'status_code': 404})

    return ans


def put_data(key, data, expiration_date, v_key, node, alt_node):
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
    v_key = int(request.args.get('v_key'))
    key = request.args.get('str_key')
    data = request.args.get('data')
    expiration_date = request.args.get('expiration_date')
    return put_in_cache(v_key, key, data, expiration_date)


def put_in_cache(v_key, key, data, expiration_date):
    try:
        # actually setting the data
        bucket = cache.get(v_key)
        if not bucket:
            bucket = {}
        bucket[key] = (data, expiration_date)
        cache[v_key] = bucket
        return json.dumps({'status code': 200,
                           'item': cache[v_key][key],
                           'ip': ip_address,
                           'v_key': v_key})

    except:
        return "failed in put_internaly"


#  get items from nodes
@app.route('/get', methods=['GET', 'POST'])
def get():
    key = request.args.get('str_key')
    v_key, node, alt_node = get_nodes(key)
    try:
        ans = requests.get(get_url(node, key, 'get', v_key), timeout=5)
        if ans.json().get('status code') == 404:
            ans = requests.get(get_url(alt_node, key, 'get', v_key), timeout=5)
    except (ConnectionError, Timeout):
        ans = requests.get(get_url(alt_node, key, 'get', v_key), timeout=5)
        return ans.json()
    return ans.json()


@app.route('/get_internaly', methods=['GET', 'POST'])
def get_internaly():
    key = request.args.get('str_key')
    v_key = int(request.args.get('v_key'))
    # getting the data out of the cache
    try:
        item = cache[v_key][key]
        response = json.dumps({'status code': 200,
                               'item': item[0],
                               'ip': ip_address,
                               'v_key': v_key})
    except:
        response = json.dumps({'status code': 404,
                               'item': "item does not exists"})
    return response


@app.route('/get_all', methods=['GET', 'POST'])
def get_all():
    buffer = cache.copy()
    buffer['nodes'] = live_nodes_list
    buffer['num node'] = live_nodes_pool_size
    return json.dumps(buffer)


if __name__ == '__main__':
    ip_address = requests.get('https://api.ipify.org').text
    print('My public IP address is: {}'.format(ip_address))
    app.run(host='0.0.0.0', port=8080)
