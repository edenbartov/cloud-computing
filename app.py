import json
import xxhash
from datetime import datetime
from flask import Flask, request
import requests
import boto3
import threading
import time
import socket
import logging


dynamodb = boto3.resource('dynamodb',region_name="us-east-1")
table = dynamodb.Table('LivingNodes')
cache = {}
app = Flask(__name__)
delay_period = 30
last = 0 
ip_address = ""
logger = logging.getLogger('werkzeug') # grabs underlying WSGI logger
handler = logging.FileHandler('test.log') # creates handler for the log file
logger.addHandler(handler) # adds handler to the werkzeug WSGI logger


@app.route('/health-check', methods=['GET', 'POST'])
def health_check():
    timestamp = get_milis(datetime.now())
    item = {'ip': ip_address,
        'lastAlive': timestamp
        }
    table.put_item(Item=item)
    return f'it is I {ip_address} - at time {timestamp} im still alive'



def get_live_node_list():
    try:
        app.logger.info('get_live_node_list')
        now = datetime.now()
        past_periond = now - datetime.timedelta(seconds=delay_period)
        response = table.query(
            KeyConditionExpression=Key('lastAlive').between(get_milis(past_periond), get_milis(now))
        )
        app.logger.info(f'get_live_node_list-  responde: {response}')
        return (x['ip'] for x in response['items'])
    except:
            app.logger.info(f'error in get_live_node_list')
            return "failed in the get_live_node_list"

def get_milis(dt):
    return (int(round(dt.timestamp() * 1000)))

def get_nodes(key):
    try:
        app.logger.info(f'get_nodes')
        nodes = get_live_node_list()
        temp_key = xxhash.xxh64_intdigest(key) % 1024
        node = nodes[(temp_key % len(nodes))]
        alt_node = nodes[((temp_key + 1) % len(nodes))]
        app.logger.info(f'get_nodes: node: {node}, nodes: {nodes}')
        return node, alt_node
    except:
        app.logger.info(f'failed in the get_nodes')
        return "failed in the get_nodes"


def get_url(node, key, op, data=None, expiration_date=None):
    if op == 'put':
        return f'http://{node}:8080/{op}_internaly?str_key={key}&data={data}&expiration_date={expiration_date}'
    else:
        return f'http://{node}:8080/{op}_internaly?str_key={key}'


@app.route('/put', methods=['GET', 'POST'])
def put():
    try:
        app.logger.info(f'put')

        key = request.args.get('str_key')
        data = request.args.get('data')
        expiration_date = request.args.get('expiration_date')
        
        node, alt_node =  get_nodes(key)
    except:
        app.logger.info(f'failed in the put when getting the arguments')
        return "failed in the put when getting the arguments"
    try:
        app.logger.info(f'tring to send request to other node')
        ans = requests.post(get_url(node,key,'put',data,expiration_date))
        ans = requests.post(get_url(alt_node,key,'put',data,expiration_date))
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
    try:
        key = request.args.get('str_key')
        data = request.args.get('data')
        expiration_date = request.args.get('expiration_date')
        #actually seting the data
        cache[key] = (data, expiration_date)
        print(cache)
        return json.dumps({'status code': 200,
                           'item': cache[key]})
    except:
        return "failed in put_internaly"

@app.route('/get_internaly', methods=['GET', 'POST'])
def get_internaly():
    key = request.args.get('str_key')
    # getting the data out of the cache
    item = cache[key]
    response = json.dumps({'status code': 200,
                           'item': item[0]})
    return response


@app.route('/test', methods=['GET', 'POST'])
def test():
    func = request.args.get('func')
    # getting the data out of the cache
    if func == 'get_live_node_list':
        item = get_live_node_list()
    elif func == 'get_nodes':
        item,_ = get_nodes()
    response = json.dumps({'status code': 200,
                           'item': item})
    return response
  
if __name__ == '__main__':
    ip_address = requests.get('https://api.ipify.org').text
    print('My public IP address is: {}'.format(ip_address)) 
    app.run(host='0.0.0.0', port=8080,debug=True)
