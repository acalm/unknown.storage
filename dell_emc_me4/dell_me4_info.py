#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2020, Andreas Calminder
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from ansible.module_utils.basic import AnsibleModule
import copy
import hashlib
import os
import re
import requests

ANSIBLE_METADATA = {
    'metadata_version': '0.1',
    'status': ['preview'],
    'supported_by': 'none'
}
DOCUMENTATION = '''
---
module: dell_me4_facts
short_description: Get facts from Dell EMC me4 series SAN
description:
  - This module gathers facts from Dell EMC ME4 SAN
requirements:
  - "python >= 3.6"
  - requests
author:
  - Andreas Calminder (@acalm)
notes:
  - Tested on Dell EMC ME4024
options:
  hostname:
    required: True
    description:
      - management endpoint
    type: str
  username:
    default: manage
    description:
      - username for logging in to san management
    type: str
  password:
    required: True
    description:
      - password for logging in to san management
    type: str
  verify_cert:
    default: True
    description:
      - verify certificate(s) when connecting to san management
    type: bool
'''


def get_session_key(module):
    rv = False
    auth = hashlib.sha256('{username}_{password}'.format(**module.params).encode('utf-8')).hexdigest()
    url = 'https://{0}/api/login/{1}'.format(module.params['hostname'], auth)
    headers = {'datatype': 'json'}
    r = requests.get(url, headers=headers, verify=module.params['verify_cert'])
    if not r.ok:
        return rv

    rv = r.json()['status'][0]['response']
    return rv


def make_request(url, headers, module):
    default_headers = {'datatype': 'json'}
    headers.update(default_headers)
    r = requests.get(url=url, headers=headers, verify=module.params['verify_cert'])
    if not r.ok:
        module.fail_json(msg='{0} returned status code {1}: {2}'.format(url, r.status_code, r.reason))

    ret = r.json()

    status = ret.get('status', [])[0]
    if not status.get('return-code') == 0:
        module.fail_json(msg='{0} returned abnormal status, response: {1}, response type: {2}, return code: {3}'.format(url, status.get('response'), status.get('response-type'), status.get('return-code')))

    return ret


def get_iscsi_parameters(session_key, module):
    url = 'https://{0}/api/show/iscsi-parameters'.format(module.params['hostname'])
    headers = {'sessionKey': session_key}
    ret = make_request(url, headers, module)
    return ret.get('iscsi-parameters', [])


def get_controllers(session_key, module):
    url = 'https://{0}/api/show/controllers'.format(module.params['hostname'])
    headers = {'sessionKey': session_key}
    ret = make_request(url, headers, module)
    return ret.get('controllers', [])


def get_disks(session_key, module):
    url = 'https://{0}/api/show/disks'.format(module.params['hostname'])
    headers = {'sessionKey': session_key}
    ret = make_request(url, headers, module)
    return ret.get('drives', [])


def get_disk_groups(session_key, module):
    url = 'https://{0}/api/show/disk-groups'.format(module.params['hostname'])
    headers = {'sessionKey': session_key}
    ret = make_request(url, headers, module)
    return ret.get('disk-groups', [])


def get_volumes(session_key, module):
    url = 'https://{0}/api/show/volumes'.format(module.params['hostname'])
    headers = {'sessionKey': session_key}
    ret = make_request(url, headers, module)
    return ret.get('volumes', [])


def get_pools(session_key, module):
    url = 'https://{0}/api/show/pools'.format(module.params['hostname'])
    headers = {'sessionKey': session_key}
    ret = make_request(url, headers, module)
    return ret.get('pools', [])


def get_ports(session_key, module):
    url = 'https://{0}/api/show/ports'.format(module.params['hostname'])
    headers = {'sessionKey': session_key}
    ret = make_request(url, headers, module)
    return ret.get('port', [])


def get_system(session_key, module):
    url = 'https://{0}/api/show/system'.format(module.params['hostname'])
    headers = {'sessionKey': session_key}
    ret = make_request(url, headers, module)
    return ret.get('system', [])


def get_host_groups(session_key, module):
    url = 'https://{0}/api/show/host-groups'.format(module.params['hostname'])
    headers = {'sessionKey': session_key}
    ret = make_request(url, headers, module)
    return ret.get('host-group', [])


def get_users(session_key, module):
    url = 'https://{0}/api/show/users'.format(module.params['hostname'])
    headers = {'sessionKey': session_key}
    ret = make_request(url, headers, module)
    return ret.get('users', [])


def add_me4_info(me4_dict):
    rv = {}
    # add size in bytes
    block_keys = ['blocksize', 'blocks']
    if all([me4_dict.get(k) for k in block_keys]) and all([isinstance(me4_dict.get(k), int) for k in block_keys]):
        rv['size_in_bytes'] = me4_dict['blocksize'] * me4_dict['blocks']

    if me4_dict.get('raidtype-numeric'):
        rv['raid_num'] = me4_dict.get('raidtype-numeric')

    if me4_dict.get('progress-numeric'):
        rv['progress_num'] = me4_dict.get('progress-numeric')

    return rv


def gen_me4_info(module):
    rv = {'disks': [], 'system': {}, 'volumes': [], 'ports': [], 'disk_groups': [], 'pools': [], 'iscsi_parameters': {}, 'users': [], 'host_groups': []}
    session_key = get_session_key(module)
    disks = get_disks(session_key, module)
    system = get_system(session_key, module)
    volumes = get_volumes(session_key, module)
    ports = get_ports(session_key, module)
    disk_groups = get_disk_groups(session_key, module)
    pools = get_pools(session_key, module)
    host_groups = get_host_groups(session_key, module)

    rv['system'] = mangle_me4_dict(system[0])
    rv['iscsi_parameters'] = mangle_me4_dict(get_iscsi_parameters(session_key, module)[0])
    rv['host_groups'] = [mangle_me4_dict(group) for group in host_groups]
    rv['users'] = [mangle_me4_dict(user) for user in get_users(session_key, module)]

    for disk in disks:
        disk_mangled = mangle_me4_dict(disk)
        disk_mangled['name'] = disk['location']
        disk_mangled.update(add_me4_info(disk))
        rv['disks'].append(disk_mangled)

    for volume in volumes:
        volume_mangled = mangle_me4_dict(volume)
        volume_mangled.update(add_me4_info(volume))
        rv['volumes'].append(volume_mangled)

    for port in ports:
        if port.get('iscsi-port'):
            port.update(port['iscsi-port'][0])
            del port['iscsi-port']
        if port.get('fc-port'):
            port.update(port['fc-port'][0])
            del port['fc-port']
        rv['ports'].append(mangle_me4_dict(port))

    for group in disk_groups:
        mangled_group = mangle_me4_dict(group)
        mangled_group.update(add_me4_info(group))
        rv['disk_groups'].append(mangled_group)

    for pool in pools:
        dg_names = [d.get('name') for d in pool.get('disk-groups', [])]
        if pool.get('disk-groups'):
            del pool['disk-groups']
            pool['disk_groups'] = dg_names
        rv['pools'].append(mangle_me4_dict(pool))

    return rv


def mangle_me4_dict(me4_dict):
    rv = {}
    ignores = ['object-name', 'meta']

    for k in me4_dict:
        if k in ignores:
            continue
        if k.endswith('-numeric'):
            continue
        if isinstance(me4_dict[k], list):
            _k = k.replace('-', '_')
            rv[_k] = []
            for i in me4_dict[k]:
                if isinstance(i, dict):
                    rv[_k].append(mangle_me4_dict(i))
            continue
        if isinstance(me4_dict[k], dict):
            rv[k.replace('-', '_')] = mangle_me4_dict(me4_dict[k])
            continue
        rv[k.replace('-', '_')] = me4_dict[k]
    return rv


def main():
    module = AnsibleModule(
        argument_spec=dict(
            hostname=dict(type='str', required=True),
            verify_cert=dict(type='bool', default=True),
            username=dict(type='str', default='manage'),
            password=dict(type='str', required=True, no_log=True),

        ),
        supports_check_mode=True
    )
    me4_info = gen_me4_info(module)
    module.exit_json(changed=False, me4_info=me4_info)


if __name__ == '__main__':
    main()