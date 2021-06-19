import redis
import json
import xxhash
from datetime import datetime
from flask import Flask, request
import requests
import boto3
import threading
import socket

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('LivingNodes',endpoint_url="http://localhost:8000")
cache = {}
app = Flask(__name__)
delay_period = 15
last = 0 

def signal_alive():
    timestamp = get_milis(datetime.now())
    ip = socket.gethostbyname(socket.gethostname())
    print(timestamp)
    item = {'ip': ip,
            'lastAlive': timestamp
            }
    table.put_item(Item=item)

def get_live_node_list():
    # response = table.scan()
    now = datetime.now()
    past_periond = now - datetime.timedelta(seconds=delay_period)
    response = table.query(
        KeyConditionExpression=Key('lastAlive').between(get_milis(past_periond), get_milis(now))
    )
    return (x['ip'] for x in response['items'])

def get_milis(dt):
    int(round(dt.timestamp() * 1000))

def get_nodes(key):
    nodes = get_live_node_list()
    temp_key = xxhash.xxh64_intdigest(key) % 1024
    node = nodes[(temp_key % len(nodes))]
    alt_node = nodes[((temp_key + 1) % len(nodes))]
    return node, alt_node

def get_url(node, key, op, data=None, expiration_date=None):
    if op == 'put':
        return f'http://{node}:5000/{op}_internaly?str_key={key}&data={data}&expiration_date={expiration_date}'
    else:
        return f'http://{node}:5000/{op}_internaly?str_key={key}'


@app.route('/put', methods=['GET', 'POST'])
def put():
    key = request.args.get('str_key')
    data = request.args.get('data')
    expiration_date = request.args.get('expiration_date')
    
    node, alt_node =  get_nodes(key)

    try:
        ans = requests.post(get_url(node,key,'put',data,expiration_date,))
        ans = requests.post(get_url(alt_node,key,'put',data,expiration_date,))
    except:
        return json.dumps({'status_code': 404}).json()
    
    return ans.json()

#  get items from nodes
@app.route('/get', methods=['GET', 'POST'])
def get():
    key = request.args.get('str_key')

    node, alt_node = get_nodes(key)
    
    try:
        ans = requests.get(get_url(node,key,'get'))
    except:
        try:
            ans = requests.get(get_url(alt_node,key,'get'))
        except requests.exceptions.ConnectionError:
            return ans
    return ans.json().get('item')


@app.route('/put_internaly', methods=['GET', 'POST'])
def put_internaly():
    key = request.args.get('str_key')
    data = request.args.get('data')
    expiration_date = request.args.get('expiration_date')
    #actually seting the data
    cache[key] = (data, expiration_date)
    print(cache)
    return json.dumps({'status code': 200,
                       'item': cache[key]})

@app.route('/get_internaly', methods=['GET', 'POST'])
def get_internaly():
    key = request.args.get('str_key')
    # getting the data out of the cache
    item = cache[key]
    response = json.dumps({'status code': 200,
                           'item': item[0]})
    return response

now = datetime.now()
if (now.second> (last +10)%60):
    last  =  now.second
    signal_alive()

if __name__ == '__main__':
    app.run()
