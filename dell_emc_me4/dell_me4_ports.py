#!/usr/bin/env python
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from ansible.module_utils.basic import AnsibleModule
import copy
import hashlib
import ipaddress
import os
import requests

ANSIBLE_METADATA = {
    'metadata_version': '0.1',
    'status': ['alpha'],
    'supported_by': 'none'
}
DOCUMENTATION = '''
---
module: dell_me4_ports
short_description: Manage ports in a Dell EMC me4 series SAN
description:
  - Manage ports in Dell EMC PowerVault ME4xxx
requirements:
  - "python >= 3.6"
  - requests
author:
  - Andreas Calminder (@acalm)
notes:
  - Tested on Dell EMC ME4024 iscsi
options:
  fc_mode:
    choices:
      - loop
      - point-to-point
      - auto
    default: point-to-point
    description:
      - FC connection mode
      - C(loop) Fibre Channel-Arbitrated Loop
      - C(point-to-point) Fibre Channel point-to-point
      - C(auto) Automatically sets the mode based on the detected connection type
    type: str
  fc_loop_ids:
    description:
      - loop ID values to request for host ports when controllers arbitrate during a LIP
    type: list
  port:
    description:
      - port name, for example C(a0)
    required: True
  ip_address:
    description:
      - ipv4 or ipv6 ip address
      - required when using iscsi
      - using C(ipv4) mode and 0.0.0.0 disable the port for I/O
    type: str
  netmask:
    default: 255.255.255.0
    description:
      - subnet mask for the port ip address
    type: str
  gateway:
    default: 0.0.0.0
    description:
      - gateway address
    type: str
  mode:
    choices:
      - iscsi
      - fc
    default: iscsi
    description:
      - port mode, C(fc) or C(iscsi)
    type: str
  fc_speed:
    choices:
      - 4g
      - 8g
      - 16g
      - auto
    default: auto
    description:
      - sets a forced link speed in Gbit/s
      - loop mode cannot be used with 16g link speed.
    type: str
  default_router:
    description:
      - ipv6 only, the default router for the port ip address
    type: str
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


def get_ports(session_key, module):
    url = 'https://{0}/api/show/ports'.format(module.params['hostname'])
    headers = {'sessionKey': session_key}
    ret = make_request(url, headers, module)
    return ret.get('port', [])


def configure_iscsi_port(module):
    changed = False
    diff = {'before': {}, 'after': {}}
    msg = 'no change'
    base_url = 'https://{0}/api/set/host-parameters/'.format(module.params['hostname'])

    if not module.params['ip_address']:
        module.fail_json(msg='ip_address is required when type: iscsi')
    try:
        ipaddr = ipaddress.ip_address(module.params['ip_address'])
    except ValueError:
        module.fail_json(msg='{0} does not appear to be an ipv4 or ipv6 address'.format(module.params['ip_address']))
    ip_version = 'ipv{0}'.format(ipaddr.version)
    session_key = get_session_key(module)
    ports = get_ports(session_key, module)

    for port in ports:
        if module.params['port'].lower() == port.get('port', '').lower():
            if port.get('port-type').lower() != module.params['mode']:
                module.exit_json(msg='incorrect port type {0} for port {1}'.format(port.get('port-type').lower(), module.params['port']))
            current_config = port.get('iscsi-port', [])[0]
            diff['before'] = current_config

            if ipaddr.version == 4:
                cmd = ''
                if not all(
                    [
                        module.params['ip_address'] == port.get('ip-address'),
                        module.params['gateway'] == port.get('gateway'),
                        module.params['netmask'] == port.get('netmask'),
                    ]
                ):
                    cmd = os.path.join(cmd, 'ip', module.params['ip_address'], 'netmask', module.params['netmask'], 'gateway', module.params['gateway'], 'iscsi-ip-version', ip_version, 'ports', module.params['port'])
                if cmd:
                    headers = {'sessionKey': session_key}
                    url = os.path.join(base_url, cmd)
                    if module.check_mode:
                        changed = True
                        msg = 'port {0} updated (check mode)'.format(module.params['port'])
                        diff['after'] = copy.deepcopy(current_config)
                        diff['after'].update(
                            {
                                'ip-address': module.params['ip_address'],
                                'gateway': module.params['gateway'],
                                'netmask': module.params['netmask'],
                                'ip-version': ip_version
                            }
                        )
                        port_out = copy.deepcopy(port)
                        port_out['iscsi-port'] = [diff['after']]
                        return changed, diff, msg, port_out
                    ret = make_request(url, headers, module)
                    msg = ret['status'][0]['response']
                    changed = True

            if ipaddr.version == 6:
                cmd = ''
                if module.params['default_router'] and module.params['default_router'] != port.get('default_router'):
                    cmd = os.path.join(cmd, 'default-router', module.params['default_router'])
                if port.get('ip-address').lower() != module.params['ip-address'].lower():
                    cmd = os.path.join(cmd, 'ip', module.params['ip_address'])

                if cmd:
                    headers = {'sessionKey': session_key}
                    cmd = os.path.join(cmd, 'iscsi-ip-version', ip_version, 'ports', module.params['port'])
                    url = os.path.join(base_url, cmd)
                    if module.check_mode:
                        changed = True
                        msg = 'port {0} updated (check mode)'.format(module.params['port'])
                        diff['after'] = copy.deepcopy(current_config)
                        diff['after'].update(
                            {
                                'ip-address': module.params['ip_address'],
                                'default-router': module.params.get('default_router', port.get('default-router')),
                                'ip-version': ip_version
                            }
                        )
                        port_out = copy.deepcopy(port)
                        port_out['iscsi-port'] = [diff['after']]
                        return changed, diff, msg, port_out

                    ret = make_request(url, headers, module)
                    msg = ret['status'][0]['response']
                    changed = True

    _rp = [x for x in get_ports(session_key, module) if x.get('port', '').lower() == module.params['port'].lower()]
    if changed:
        diff['after'] = _rp[0].get('iscsi-port', [])[0]
    return changed, diff, msg, _rp[0]


def configure_fc_port(module):
    module.fail_json(msg='not implemented yet')
    changed = False
    diff = {'before': {}, 'after': {}}
    msg = 'no change'
    loop_ids = []
    port_name = module.params['port'].lower()

    if module.params['fc_mode'] == 'loop' and module.params['fc_speed'] == '16g':
        module.fail_json(msg='cannot use loop with 16g speed ')

    if module.params['fc_loop_ids']:
        loop_ids = sorted(module.params['fc_loop_ids'])

    session_key = get_session_key(module)
    ports = get_ports(session_key, module)

    for port in ports:
        if port.get('port').lower() == port_name:
            cmd = ''


def main():
    module = AnsibleModule(
        argument_spec=dict(
            hostname=dict(type='str', required=True),
            verify_cert=dict(type='bool', default=True),
            username=dict(type='str', default='manage'),
            password=dict(type='str', required=True, no_log=True),
            fc_mode=dict(type='str', choices=['loop', 'point-to-point', 'auto'], default='point-to-point'),
            fc_loop_ids=dict(type='list'),
            port=dict(type='str', required=True),
            ip_address=dict(type='str'),
            netmask=dict(type='str', default='255.255.255.0'),
            gateway=dict(type='str', default='0.0.0.0'),
            mode=dict(type='str', choices=['fc', 'iscsi'], default='iscsi'),
            fc_speed=dict(type='str', choices=['4g', '8g', '16g', 'auto'], default='auto'),
            default_router=dict(type='str')
        ),
        supports_check_mode=True
    )

    if module.params['mode'] == 'iscsi':
        changed, diff, msg, port = configure_iscsi_port(module)

    if module.params['mode'] == 'fc':
        module.exit_json(changed=False, msg='not implemented yet')

    module.exit_json(changed=changed, diff=diff, msg=msg, port=port)


if __name__ == '__main__':
    main()