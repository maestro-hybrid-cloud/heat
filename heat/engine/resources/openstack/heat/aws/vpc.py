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
from heat.engine import properties
from heat.engine.resources.openstack.heat.aws import BotoResource

class VPC(BotoResource):

    PROPERTIES = (
        CIDR_BLOCK, INSTANCE_TENANCY, TAGS,
    ) = (
        'CidrBlock', 'InstanceTenancy', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        CIDR_BLOCK: properties.Schema(
            properties.Schema.STRING,
            _('CIDR block to apply to the VPC.')
        ),
        INSTANCE_TENANCY: properties.Schema(
            properties.Schema.STRING,
            _('Allowed tenancy of instances launched in the VPC. default - '
              'any tenancy; dedicated - instance will be dedicated, '
              'regardless of the tenancy option specified at instance '
              'launch.'),
            default='default'
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of tags to attach to the instance.'),
                schema={
                    TAG_KEY: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    TAG_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
                implemented=False
            )
        ),
    }

    def handle_create(self):
        client = self.vpc()

        cidr_block = self.properties.get(self.CIDR_BLOCK)
        instance_tenancy = self.properties.get(self.INSTANCE_TENANCY)

        vpc = client.create_vpc(cidr_block, instance_tenancy)
        if vpc:
            self.resource_id_set(vpc.id)

    def check_create_complete(self, *args):
        vpcs = self.vpc().get_all_vpcs(vpc_ids=[self.resource_id])
        if vpcs and len(vpcs) > 0:
            status = vpcs[0].state
            if status == 'available':
                return True
        return False

    def handle_delete(self):
        if self.resource_id is None:
            return

        client = self.vpc()
        client.delete_vpc(self.resource_id)

def resource_mapping():
    return {
        'AWS::VPC::VPC': VPC,
    }