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


import boto.ec2
import boto.vpc

from heat.engine import resource

class BotoResource(resource.Resource):

    def __init__(self, name, json_snippet, stack):
        super(BotoResource, self).__init__(name, json_snippet, stack)
        self._ec2_conn = None
        self._vpc_conn = None

    def ec2(self):
        if self._ec2_conn is None:
            self._ec2_conn = boto.ec2.EC2Connection()
        return self._ec2_conn

    def vpc(self):
        if self._vpc_conn is None:
            self._vpc_conn = boto.vpc.VPCConnection()
        return self._vpc_conn
