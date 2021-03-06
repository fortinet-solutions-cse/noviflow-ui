#!/usr/bin/python3
from flask import Flask, Response, request, jsonify
from random import random
from apscheduler.schedulers.background import BackgroundScheduler
from json import loads, dumps
import grequests
import requests
import gevent
import paramiko
import traceback

# Note previous patch to avoid error with paramiko
# and grequests: https://github.com/paramiko/paramiko/issues/633

from gevent import monkey
import time

monkey.patch_all()

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# This requires glances to run on the hypervisors
# install the package and run: glances -w & disown
#
# Ensure ports are open in the server (CentOS 7):
# firewall-cmd --zone=public --permanent --add-port=61208/tcp
# firewall-cmd --reload


# Urls to access FGT REST API
urls_fgt = [
    'https://10.210.14.33/',
    'https://10.210.14.34/',
    'https://10.210.14.100/',
    'https://10.210.14.101/',
    'https://10.210.14.102/',
    'https://10.210.14.103/'
]

# URLs to access hypervisor REST API (cpu load)
urls_hypervisors = [
    'http://10.210.14.18:61208/api/2/cpu',
    'http://10.210.14.6:61208/api/2/cpu',
    'http://10.210.14.22:61208/api/2/cpu',
    'http://10.210.14.23:61208/api/2/cpu'
]

# Address of the hypervisor of each fortigate
fgt_hypervisors = [
    '10.210.14.18',
    '10.210.14.6',
    '10.210.14.22',
    '10.210.14.22',
    '10.210.14.23',
    '10.210.14.23',
    '127.0.0.1',
    '127.0.0.1'
]

url_cybermapper = 'http://10.210.9.132:8080'

FTS1_IP = "10.210.1.28"
FTS2_IP = "10.210.1.29"

FTS1_CASE_ID = '5b02db2ddfaa0f02ec656c76'
FTS2_CASE_ID = '5b02d8acac929f0348c9c9d0'
FTS_CPS_PER_VM = 5200

TIMEOUT = 3
POLL_INTERVAL = 4
USER_FGT = 'admin'
PASSWORD_FGT = ''
USERNAME_HYPERVISOR = 'root'
KEEP_DATA = 1

MAX_NUMBER_OF_SAMPLES = 300

fgt_sessions = [requests.Session() for u in urls_fgt]

data_cpuload_time1 = [-1] * 60
data_cpuload_time2 = [-1] * 60
data_cpuload_time3 = [-1] * 60
data_cpuload_time4 = [-1] * 60
data_fgtload_time1 = [-1] * 60
data_fgtload_time2 = [-1] * 60
data_fgtload_time3 = [-1] * 60
data_fgtload_time4 = [-1] * 60
data_fgtload_time5 = [-1] * 60
data_fgtload_time6 = [-1] * 60

data_totalthroughput_ingress_time = [-1] * 60
data_totalthroughput_egress_time = [-1] * 60

data_fgtthroughput1_time = [-1] * 60
data_fgtthroughput2_time = [-1] * 60
data_fgtthroughput3_time = [-1] * 60
data_fgtthroughput4_time = [-1] * 60
data_fgtthroughput5_time = [-1] * 60
data_fgtthroughput6_time = [-1] * 60


def push_value_to_list(list, value):
    list.append(float("{0:.2f}".format(value)))
    if list[0] <= -1 or not KEEP_DATA or len(list) > MAX_NUMBER_OF_SAMPLES:
        del list[0]


@app.route("/start_vm", methods=['POST'])
def start_vm():
    try:
        response = Response()
        response.headers.add('Access-Control-Allow-Origin', '*')

        fgt_id = request.args.get('fgt')
        fgt_id = int(fgt_id)

        returned_str = execute_start_vm(fgt_id)

        time.sleep(40)

        returned_str += execute_add_target(fgt_id)

        # Increase traffic load FTS1
        time.sleep(5)

        headers = {
            'Content-Type': "application/json",
        }

        url_fts = "http://" + FTS1_IP + "/api/networkLimit/modify"
        fts_data = '{"config": { \
                       "SpeedLimit": ' + str(fgt_id * FTS_CPS_PER_VM / 2) + ', \
                       "RampUpSecond": "0", \
                       "RampDownSecond": "0", \
                       "TestType": "HttpCps", \
                       "LimitType": "speed"}, \
                    "order": 0}'

        results = requests.post(url_fts,
                                data=fts_data,
                                headers=headers,
                                timeout=TIMEOUT)

        returned_str += "<br><b>FortiTester1 response (code): </b>" + str(results.status_code)
        returned_str += "<br><b>FortiTester1 response (content): </b>" + \
                        str(dumps(loads(results.content.decode('utf-8')),
                                  indent=4,
                                  sort_keys=True).replace('\n', '<br>').replace(' ', '&nbsp;'))

        # Increase traffic load FTS2
        url_fts = "http://" + FTS2_IP + "/api/networkLimit/modify"
        results = requests.post(url_fts,
                                data=fts_data,
                                headers=headers,
                                timeout=TIMEOUT)

        returned_str += "<br><b>FortiTester2 response (code): </b>" + str(results.status_code)
        returned_str += "<br><b>FortiTester2 response (content): </b>" + \
                        str(dumps(loads(results.content.decode('utf-8')),
                                  indent=4,
                                  sort_keys=True).replace('\n', '<br>').replace(' ', '&nbsp;'))

        response.data = returned_str
        return response

    except:
        response.data = returned_str + traceback.format_exc()
        return response


@app.route("/stop_vm", methods=['POST'])
def stop_vm():

    try:
        response = Response()
        response.headers.add('Access-Control-Allow-Origin', '*')

        fgt_id = request.args.get('fgt')
        fgt_id = int(fgt_id)

        # Decrease traffic load FTS1
        headers = {
            'Content-Type': "application/json",
        }

        url_fts = "http://" + FTS1_IP + "/api/networkLimit/modify"
        fts_data = '{"config": { \
                       "SpeedLimit": ' + str((fgt_id - 1) * FTS_CPS_PER_VM / 2) + ', \
                       "RampUpSecond": "0", \
                       "RampDownSecond": "0", \
                       "TestType": "HttpCps", \
                       "LimitType": "speed"}, \
                    "order": 0}'

        results = requests.post(url_fts,
                                data=fts_data,
                                headers=headers,
                                timeout=TIMEOUT)

        returned_str = "<b>FortiGate id: </b>" + str(fgt_id) + "<br>" + \
                       "<b>FortiTester1 response (code): </b>" + str(results.status_code) + \
                       "<br><b>FortiTester1 response (content): </b>" + \
                       str(dumps(loads(results.content.decode('utf-8')),
                                 indent=4,
                                 sort_keys=True).replace('\n', '<br>').replace(' ', '&nbsp;'))

        # Decrease traffic load FTS2
        url_fts = "http://" + FTS2_IP + "/api/networkLimit/modify"

        results = requests.post(url_fts,
                                data=fts_data,
                                headers=headers,
                                timeout=TIMEOUT)

        returned_str += "<b>FortiTester2 response (code): </b>" + str(results.status_code) + \
                        "<br><b>FortiTester2 response (content): </b>" + \
                        str(dumps(loads(results.content.decode('utf-8')),
                                  indent=4,
                                  sort_keys=True).replace('\n', '<br>').replace(' ', '&nbsp;'))

        time.sleep(1)

        returned_str += execute_remove_target(fgt_id)

        time.sleep(10)

        # StopVm
        returned_str += execute_stop_vm(fgt_id)

        response.data = returned_str

        return response

    except:
        response.data = returned_str + traceback.format_exc()
        return response


@app.route("/start_traffic", methods=['POST'])
def start_traffic():
    response = Response()
    response.headers.add('Access-Control-Allow-Origin', '*')

    # Login FTS1
    url = "http://" + FTS1_IP + "/api/user/login"

    payload = '{ "name":"admin", "password":"" }'
    headers = {"Content-Type": "application/json",
               "Cache-Control": "no-cache"}

    result_login_fts1 = requests.post(url,
                                      data=payload,
                                      timeout=TIMEOUT,
                                      headers=headers,
                                      verify=False)

    # Login FTS2
    url = "http://" + FTS2_IP + "/api/user/login"

    result_login_fts2 = requests.post(url,
                                      data=payload,
                                      timeout=TIMEOUT,
                                      headers=headers,
                                      verify=False)

    # Start case FTS1
    url = "http://" + FTS1_IP + "/api/case/" + FTS1_CASE_ID + "/start"

    if result_login_fts1.status_code == 200:
        result_start_fts1 = requests.get(url,
                                         timeout=TIMEOUT,
                                         cookies=result_login_fts1.cookies,
                                         verify=False)

        if result_start_fts1.status_code == 200:
            returned_str = "<b>Success.</b> Traffic started in FortiTester1."
        else:
            returned_str = "<b>Error:</b> Could not start traffic in FortiTester1. <br>" + \
                           " Code: " + str(result_start_fts1.status_code) + " Text: " + result_start_fts1.text
    else:
        returned_str = "<b>Error:</b> Could not log in to FortiTester1. <br> " + \
                       " Code: " + str(result_login_fts1.status_code) + " Text: " + strresult_login_fts1.text

    # Start case FTS2
    url = "http://" + FTS2_IP + "/api/case/" + FTS2_CASE_ID + "/start"

    if result_login_fts2.status_code == 200:
        result_start_fts2 = requests.get(url,
                                         timeout=TIMEOUT,
                                         cookies=result_login_fts2.cookies,
                                         verify=False)

        if result_start_fts2.status_code == 200:
            returned_str += "<br><b>Success.</b> Traffic started in FortiTester2."
        else:
            returned_str += "<br><b>Error:</b> Could not start traffic in FortiTester2. <br>" + \
                            " Code: " + str(result_start_fts2.status_code) + " Text: " + str(result_start_fts2.text)
    else:
        returned_str += "<br><b>Error:</b> Could not log in to FortiTester2. <br> " + \
                        " Code: " + str(result_login_fts2.status_code) + " Text: " + str(result_login_fts2.text)

    # Logout FTS1
    url = "http://" + FTS1_IP + "/api/user/logout"

    result_logout_fts1 = requests.get(url,
                                      timeout=TIMEOUT,
                                      cookies=result_login_fts1.cookies,
                                      verify=False)

    if result_logout_fts1.status_code != 200:
        returned_str += "<br> <b>Note:</b> User was not logged out of FortiTester1."

    # Logout FTS2
    url = "http://" + FTS2_IP + "/api/user/logout"

    result_logout_fts2 = requests.get(url,
                                      timeout=TIMEOUT,
                                      cookies=result_login_fts2.cookies,
                                      verify=False)

    if result_logout_fts2.status_code != 200:
        returned_str += "<br> <b>Note:</b> User was not logged out of FortiTester2."

    response.data = returned_str

    return response


@app.route("/stop_traffic", methods=['POST'])
def stop_traffic():
    response = Response()
    response.headers.add('Access-Control-Allow-Origin', '*')

    # Login FTS1
    url = "http://" + FTS1_IP + "/api/user/login"

    payload = '{ "name":"admin", "password":"" }'
    headers = {"Content-Type": "application/json",
               "Cache-Control": "no-cache"}

    result_login_fts1 = requests.post(url,
                                      data=payload,
                                      timeout=TIMEOUT,
                                      headers=headers,
                                      verify=False)

    # Login FTS2
    url = "http://" + FTS2_IP + "/api/user/login"

    result_login_fts2 = requests.post(url,
                                      data=payload,
                                      timeout=TIMEOUT,
                                      headers=headers,
                                      verify=False)

    # Stop case FTS1
    url = "http://" + FTS1_IP + "/api/case/stop"

    if result_login_fts1.status_code == 200:
        result_start_fts1 = requests.get(url,
                                         timeout=TIMEOUT,
                                         cookies=result_login_fts1.cookies,
                                         verify=False)

        if result_start_fts1.status_code == 200:
            returned_str = "<b>Success.</b> Traffic stopped in FortiTester1."
        else:
            returned_str = "<b>Error:</b> Could not stop traffic in FortiTester1. <br>" + \
                           " Code: " + str(result_start_fts1.status_code) + " Text: " + result_start_fts1.text
    else:
        returned_str = "<b>Error:</b> Could not log in to FortiTester1. <br> " + \
                       " Code: " + str(result_login_fts1.status_code) + " Text: " + result_login_fts1.text

    # Stop case FTS2
    url = "http://" + FTS2_IP + "/api/case/stop"

    if result_login_fts2.status_code == 200:
        result_start_fts2 = requests.get(url,
                                         timeout=TIMEOUT,
                                         cookies=result_login_fts2.cookies,
                                         verify=False)

        if result_start_fts2.status_code == 200:
            returned_str += "<br><b>Success.</b> Traffic stopped in FortiTester2."
        else:
            returned_str += "<b>Error:</b> Could not stop traffic in FortiTester2. <br>" + \
                            " Code: " + str(result_start_fts2.status_code) + " Text: " + result_start_fts2.text
    else:
        returned_str += "<b>Error:</b> Could not log in to FortiTester2. <br> " + \
                        " Code: " + str(result_login_fts2.status_code) + " Text: " + result_login_fts2.text

    # Logout FTS1
    url = "http://" + FTS1_IP + "/api/user/logout"

    result_logout_fts1 = requests.get(url,
                                      timeout=TIMEOUT,
                                      cookies=result_login_fts1.cookies,
                                      verify=False)

    if result_logout_fts1.status_code != 200:
        returned_str += "<br> <b>Note:</b> User was not logged out of FortiTester1."

    # Logout FTS2
    url = "http://" + FTS2_IP + "/api/user/logout"

    result_logout_fts2 = requests.get(url,
                                      timeout=TIMEOUT,
                                      cookies=result_login_fts2.cookies,
                                      verify=False)

    if result_logout_fts2.status_code != 200:
        returned_str += "<br> <b>Note:</b> User was not logged out of FortiTester2."

    response.data = returned_str

    return response


@app.route("/reset_data", methods=['POST'])
def reset_data():
    global data_cpuload_time1, data_cpuload_time2, data_cpuload_time3, \
        data_cpuload_time4, data_fgtload_time1, data_fgtload_time2, \
        data_fgtload_time3, data_fgtload_time4, data_fgtload_time5, \
        data_fgtload_time6, data_totalthroughput_ingress_time, \
        data_totalthroughput_egress_time, data_fgtthroughput1_time, \
        data_fgtthroughput2_time, data_fgtthroughput3_time, \
        data_fgtthroughput4_time, data_fgtthroughput5_time, \
        data_fgtthroughput6_time

    data_cpuload_time1 = [-1] * 60
    data_cpuload_time2 = [-1] * 60
    data_cpuload_time3 = [-1] * 60
    data_cpuload_time4 = [-1] * 60
    data_fgtload_time1 = [-1] * 60
    data_fgtload_time2 = [-1] * 60
    data_fgtload_time3 = [-1] * 60
    data_fgtload_time4 = [-1] * 60
    data_fgtload_time5 = [-1] * 60
    data_fgtload_time6 = [-1] * 60

    data_totalthroughput_ingress_time = [-1] * 60
    data_totalthroughput_egress_time = [-1] * 60

    data_fgtthroughput1_time = [-1] * 60
    data_fgtthroughput2_time = [-1] * 60
    data_fgtthroughput3_time = [-1] * 60
    data_fgtthroughput4_time = [-1] * 60
    data_fgtthroughput5_time = [-1] * 60
    data_fgtthroughput6_time = [-1] * 60

    response = Response()
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.data = "Records emptied"
    return response


@app.route("/keep_old_data", methods=['POST'])
def keep_old_data():
    keep_data = request.args.get('value')
    try:
        keep_data = int(keep_data)
    except:
        return "Error, identifier not recognized"

    print("Parameter received:", keep_data)

    global KEEP_DATA
    KEEP_DATA = keep_data

    response = Response()
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.data = "Keeping data: " + str(KEEP_DATA)
    return response


@app.route("/status", methods=['GET'])
def status():
    newData = """{
        "cpuload_time1": """ + str(data_cpuload_time1) + """,
        "cpuload_time2": """ + str(data_cpuload_time2) + """,
        "cpuload_time3": """ + str(data_cpuload_time3) + """,
        "cpuload_time4": """ + str(data_cpuload_time4) + """,
        "fgtload_time1": """ + str(data_fgtload_time1) + """,
        "fgtload_time2": """ + str(data_fgtload_time2) + """,
        "fgtload_time3": """ + str(data_fgtload_time3) + """,
        "fgtload_time4": """ + str(data_fgtload_time4) + """,
        "fgtload_time5": """ + str(data_fgtload_time5) + """,
        "fgtload_time6": """ + str(data_fgtload_time6) + """,
        "totalthroughput_ingress_time": """ + str(data_totalthroughput_ingress_time) + """,
        "totalthroughput_egress_time": """ + str(data_totalthroughput_egress_time) + """,
        "fgtthroughput1_time": """ + str(data_fgtthroughput1_time) + """,
        "fgtthroughput2_time": """ + str(data_fgtthroughput2_time) + """,
        "fgtthroughput3_time": """ + str(data_fgtthroughput3_time) + """,
        "fgtthroughput4_time": """ + str(data_fgtthroughput4_time) + """,
        "fgtthroughput5_time": """ + str(data_fgtthroughput5_time) + """,
        "fgtthroughput6_time": """ + str(data_fgtthroughput6_time) + """
        }"""

    response = Response()
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.data = newData
    return response


@app.route("/panic", methods=['POST'])
def panic():
    try:

        response = Response()
        response.headers.add('Access-Control-Allow-Origin', '*')

        returned_str = "Panic log: <br>" + str(stop_traffic().data.decode('ascii').strip('\n')) + "<br>"

        for vm in range(2, 7):
            returned_str += "Removing target: " + str(vm) + " : " + execute_remove_target(vm)

        returned_str += "Adding target: 1 : <br>" + execute_add_target(1) + "<br>"

        for vm in range(2, 7):
            returned_str += execute_stop_vm(vm)

        returned_str += execute_start_vm(1)

        time.sleep(10)

        returned_str += "<br> Resetting charts: " + str(reset_data().data.decode('ascii').strip('\n'))

        global KEEP_DATA
        KEEP_DATA = 1

        response.data = returned_str
        return response

    except:

        response.data = returned_str + traceback.format_exc()
        return response


def request_cpu_load_from_nodes():
    # ******************************
    # Get Values from Hypervisors
    # ******************************

    global urls_hypervisors

    rs = (grequests.get(u, timeout=TIMEOUT) for u in urls_hypervisors)

    results = grequests.map(rs)
    if len(results) >= 0:
        if results[0] is not None: push_value_to_list(data_cpuload_time1,
                                                      loads(results[0].content.decode('utf-8'))['total'])
        if results[1] is not None: push_value_to_list(data_cpuload_time2,
                                                      loads(results[1].content.decode('utf-8'))['total'])
        if results[2] is not None: push_value_to_list(data_cpuload_time3,
                                                      loads(results[2].content.decode('utf-8'))['total'])
        if results[3] is not None: push_value_to_list(data_cpuload_time4,
                                                      loads(results[3].content.decode('utf-8'))['total'])

    # ******************************
    # Get Values from FortiGates
    # ******************************

    global fgt_sessions
    global urls_fgt

    fgt_login_requests = [None] * len(urls_fgt)
    fgt_cpu_requests = [None] * len(urls_fgt)

    # First, request CPU data

    for i in range(len(fgt_sessions)):
        fgt_cpu_requests[i] = grequests.get(
            urls_fgt[i] + 'api/v2/monitor/system/resource/usage?resource=cpu&interval=1-min',
            session=fgt_sessions[i],
            headers=fgt_sessions[i].headers,
            timeout=TIMEOUT,
            verify=False)

    fgt_cpu_results = grequests.map(fgt_cpu_requests)

    # Check if request failed because of login
    # If failed, then login
    print("fgt_cpu_results:", fgt_cpu_results)

    reqs = []
    for i in range(len(fgt_sessions)):
        if fgt_cpu_results[i] is not None and fgt_cpu_results[i].status_code == 401:
            print("Login into FortiGate's REST API: ", i)
            fgt_login_requests[i] = grequests.post(urls_fgt[i] + 'logincheck',
                                                   data='username=' + USER_FGT + '&secretkey=' + PASSWORD_FGT + '&ajax=1',
                                                   session=fgt_sessions[i],
                                                   timeout=TIMEOUT,
                                                   verify=False)
            r = grequests.send(fgt_login_requests[i])
            reqs.append(r)
    gevent.joinall(reqs)

    # Only if request to get CPU was 200 OK then
    # get the value and push it to the list

    for i in range(len(fgt_cpu_results)):
        if fgt_cpu_results[i] and fgt_cpu_results[i].status_code == 200:
            try:
                push_value_to_list(globals()['data_fgtload_time' + str(i + 1)],
                                   loads(fgt_cpu_results[i].content.decode('utf-8'))['results']['cpu'][0]['current'])
            except:
                print("Error getting data from FortiGate:", i)
        else:
            print("FGT request was not ok:", i)
            if fgt_cpu_results[i] is not None:
                print("  -> result: ", fgt_cpu_results[i].status_code)
            push_value_to_list(globals()['data_fgtload_time' + str(i + 1)], -1)

    # ********************************
    # Get Values from DSO CyberMapper
    # ********************************

    global url_cybermapper

    # Get dpid

    loadbal = requests.get(url_cybermapper + '/v1.0/loadbal',
                           timeout=TIMEOUT)

    # Use this notation '[*' to get the keys extracted into a list
    dpid = [*loads(loadbal.content.decode('utf-8')).keys()][0]

    # Get port statistics

    results = requests.get(url_cybermapper + '/v1.0/switch_stats/switches/' + dpid + '/port_stats',
                           timeout=TIMEOUT)

    port_stats = loads(results.content.decode('utf-8'))

    bps = {}

    for port in port_stats:
        bps[port['id']] = (port['tx_bytes'] - port['last']['tx_bytes'] +
                           port['rx_bytes'] - port['last']['rx_bytes']) / \
                          (port['timestamp'] - port['last']['timestamp'])

    # Instead of port3 (which is faulty) we use 21-24
    # Instead of port4 we use 25-28
    push_value_to_list(data_totalthroughput_ingress_time,
                       (bps[1] + bps[21] + bps[22] + bps[23] + bps[24]) / 1000000000 * 8)
    push_value_to_list(data_totalthroughput_egress_time,
                       (bps[2] + bps[25] + bps[26] + bps[27] + bps[28]) / 1000000000 * 8)

    push_value_to_list(data_fgtthroughput1_time, (bps[5] + bps[6]) / 2000000000 * 8)
    push_value_to_list(data_fgtthroughput2_time, (bps[7] + bps[8]) / 2000000000 * 8)
    push_value_to_list(data_fgtthroughput3_time, (bps[9] + bps[10]) / 2000000000 * 8)
    push_value_to_list(data_fgtthroughput4_time, (bps[11] + bps[12]) / 2000000000 * 8)
    push_value_to_list(data_fgtthroughput5_time, (bps[13] + bps[14]) / 2000000000 * 8)
    push_value_to_list(data_fgtthroughput6_time, (bps[15] + bps[16]) / 2000000000 * 8)


def execute_start_vm(fgt_id):
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.connect(fgt_hypervisors[fgt_id - 1], username=USERNAME_HYPERVISOR)
    ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(
        "LIBVIRT_DEFAULT_URI=qemu:///system virsh start fortigate" + str(fgt_id))

    stdout = ssh_stdout.read().decode('ascii').strip('\n')
    stderr = ssh_stderr.read().decode('ascii').strip('\n')

    returned_str = "<b>FortiGate id: </b>" + str(fgt_id) + "<br>" + \
                   "<b>FortiGate VM instantiation: </b>" + str(stderr).replace('\\n', '<br>') + \
                   ":" + str(stdout).replace('\\n', '<br>') + "<br>"

    return returned_str


def execute_stop_vm(fgt_id):
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.connect(fgt_hypervisors[fgt_id - 1], username=USERNAME_HYPERVISOR)
    ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(
        "LIBVIRT_DEFAULT_URI=qemu:///system virsh shutdown fortigate" + str(fgt_id))

    stdout = ssh_stdout.read().decode('ascii').strip('\n')
    stderr = ssh_stderr.read().decode('ascii').strip('\n')

    returned_str = "<b>FortiGate VM shutdown: </b>" + str(stderr).replace('\\n', '<br>') + \
                   ":" + str(stdout).replace('\\n', '<br>') + "<br>"

    return returned_str


def execute_add_target(fgt_id):

    # Get dpid
    global url_cybermapper
    loadbal = requests.get(url_cybermapper + '/v1.0/loadbal',
                           timeout=TIMEOUT)

    # Use this notation '[*' to get the keys extracted into a list
    dpid = [*loads(loadbal.content.decode('utf-8')).keys()][0]

    # Send "add target" request
    target_data = '{ \
        "type": "pair", \
        "port_ingress": ' + str(fgt_id * 2 + 3) + ', \
        "port_egress": ' + str(fgt_id * 2 + 4) + ', \
        "id": "dpi' + str(fgt_id) + '" }'

    results = requests.post(url_cybermapper + '/v1.0/loadbal/' + dpid + '/0/targets',
                            data=target_data,
                            timeout=TIMEOUT)

    returned_str = "<b>NoviFlow response (code): </b>" + str(results.status_code)

    returned_str += "<br><b>NoviFlow response (content): </b>" + \
                    str(dumps(loads(results.content.decode('utf-8')),
                              indent=4,
                              sort_keys=True).replace('\n', '<br>').replace(' ', '&nbsp;'))

    return returned_str


def execute_remove_target(fgt_id):

    # Get dpid
    global url_cybermapper
    loadbal = requests.get(url_cybermapper + '/v1.0/loadbal',
                           timeout=TIMEOUT)

    # Use this notation '[*' to get the keys extracted into a list
    dpid = [*loads(loadbal.content.decode('utf-8')).keys()][0]

    # Send "remove target" request
    results = requests.delete(url_cybermapper + '/v1.0/loadbal/' + dpid + '/0/targets/dpi' + str(fgt_id),
                              timeout=TIMEOUT)

    returned_str = "<br><b>NoviFlow response (code): </b>" + str(results.status_code) + "<br>"

    return returned_str


cron = BackgroundScheduler(daemon=True)
cron.add_job(request_cpu_load_from_nodes, 'interval', seconds=POLL_INTERVAL)
cron.start()
