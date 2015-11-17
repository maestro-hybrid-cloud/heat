#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import properties
from heat.engine.resources.openstack.heat.aws import BotoResource


class SecurityGroup(BotoResource):

    PROPERTIES = (
        GROUP_DESCRIPTION, VPC_ID, SECURITY_GROUP_INGRESS,
        SECURITY_GROUP_EGRESS,
    ) = (
        'GroupDescription', 'VpcId', 'SecurityGroupIngress',
        'SecurityGroupEgress',
    )

    _RULE_KEYS = (
        RULE_CIDR_IP, RULE_FROM_PORT, RULE_TO_PORT, RULE_IP_PROTOCOL,
        RULE_SOURCE_SECURITY_GROUP_ID, RULE_SOURCE_SECURITY_GROUP_NAME,
        RULE_SOURCE_SECURITY_GROUP_OWNER_ID,
    ) = (
        'CidrIp', 'FromPort', 'ToPort', 'IpProtocol',
        'SourceSecurityGroupId', 'SourceSecurityGroupName',
        'SourceSecurityGroupOwnerId',
    )

    _rule_schema = {
        RULE_CIDR_IP: properties.Schema(
            properties.Schema.STRING
        ),
        RULE_FROM_PORT: properties.Schema(
            properties.Schema.STRING
        ),
        RULE_TO_PORT: properties.Schema(
            properties.Schema.STRING
        ),
        RULE_IP_PROTOCOL: properties.Schema(
            properties.Schema.STRING
        ),
        RULE_SOURCE_SECURITY_GROUP_ID: properties.Schema(
            properties.Schema.STRING,
        ),
        RULE_SOURCE_SECURITY_GROUP_NAME: properties.Schema(
            properties.Schema.STRING,
        ),
        RULE_SOURCE_SECURITY_GROUP_OWNER_ID: properties.Schema(
            properties.Schema.STRING,
        ),
    }

    properties_schema = {
        GROUP_DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the security group.'),
            required=True
        ),
        VPC_ID: properties.Schema(
            properties.Schema.STRING,
            _('Physical ID of the VPC. Not implemented.')
        ),
        SECURITY_GROUP_INGRESS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of security group ingress rules.'),
                schema=_rule_schema,
            ),
            update_allowed=True
        ),
        SECURITY_GROUP_EGRESS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of security group egress rules.'),
                schema=_rule_schema,
            ),
            update_allowed=True
        ),
    }

    def _prop_rules_to_common(self, props, direction):
        rules = []
        for pr in props[direction]:
            rule = dict(pr)
            rule.pop(self.RULE_SOURCE_SECURITY_GROUP_OWNER_ID)
            from_port = pr.get(self.RULE_FROM_PORT)
            if from_port is not None:
                from_port = int(from_port)
                if from_port < 0:
                    from_port = None
            rule[self.RULE_FROM_PORT] = from_port
            to_port = pr.get(self.RULE_TO_PORT)
            if to_port is not None:
                to_port = int(to_port)
                if to_port < 0:
                    to_port = None
            rule[self.RULE_TO_PORT] = to_port
            if (pr.get(self.RULE_FROM_PORT) is None and
                    pr.get(self.RULE_TO_PORT) is None):
                rule[self.RULE_CIDR_IP] = None
            else:
                rule[self.RULE_CIDR_IP] = pr.get(self.RULE_CIDR_IP)
            rule[self.RULE_SOURCE_SECURITY_GROUP_ID] = (
                pr.get(self.RULE_SOURCE_SECURITY_GROUP_ID) or
                pr.get(self.RULE_SOURCE_SECURITY_GROUP_NAME)
            )
            rule.pop(self.RULE_SOURCE_SECURITY_GROUP_NAME)
            rules.append(rule)
        return rules

    def create_rule(self, rule):
        src_security_group_name = rule.get(self.RULE_SOURCE_SECURITY_GROUP_NAME)
        src_security_group_owner_id = rule.get(self.RULE_SOURCE_SECURITY_GROUP_OWNER_ID)
        ip_protocol = rule.get(self.RULE_IP_PROTOCOL)
        from_port = rule.get(self.RULE_FROM_PORT)
        to_port = rule.get(self.RULE_TO_PORT)
        cidr_ip = rule.get(self.RULE_CIDR_IP)
        group_id = self.resource_id
        src_security_group_group_id = rule.get(self.RULE_SOURCE_SECURITY_GROUP_ID)

        if rule['direction'] == 'ingress':
            self.vpc().authorize_security_group(src_security_group_name=src_security_group_name,
                                                src_security_group_owner_id=src_security_group_owner_id,
                                                ip_protocol=ip_protocol, from_port=from_port, to_port=to_port,
                                                cidr_ip=cidr_ip, group_id=group_id,
                                                src_security_group_group_id=src_security_group_group_id)
        else:
            self.vpc().authorize_security_group_egress(group_id=group_id, ip_protocol=ip_protocol,
                                                       from_port=from_port, to_port=to_port,
                                                       src_group_id=src_security_group_group_id,
                                                       cidr_ip=cidr_ip)

    def handle_create(self):
        name = self.stack.name
        description = self.properties.get(self.GROUP_DESCRIPTION)
        vpc_id = self.properties.get(self.VPC_ID)

        security_group = self.vpc().create_security_group(name, description, vpc_id)
        if security_group:
            self.resource_id_set(security_group.id)

            if self.properties[self.SECURITY_GROUP_INGRESS]:
                rules_in = self._prop_rules_to_common(
                    self.properties, self.SECURITY_GROUP_INGRESS)
                for rule in rules_in:
                    rule['direction'] = 'ingress'
                    self.create_rule(rule)

            if self.properties[self.SECURITY_GROUP_EGRESS]:
                rules_e = self._prop_rules_to_common(
                    self.properties, self.SECURITY_GROUP_EGRESS)
                for rule in rules_e:
                    rule['direction'] = 'egress'
                    self.create_rule(rule)

    def handle_delete(self):
        if self.resource_id is None:
            return

        self.vpc().delete_security_group(group_id=self.resource_id)

def resource_mapping():
    return {
        'AWS::VPC::SecurityGroup': SecurityGroup,
    }