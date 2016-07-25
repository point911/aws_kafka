#!/usr/bin/env python

import os
import copy
import yaml
import argparse
import collections


from boto import ec2
from yaml.representer import Representer

AWS_HOSTS_FILE_PATH = 'vars/aws/aws.yaml'
METAVARS_PATH = './metavars.yaml'

AWS_ACCESS_KEY_ID = os.environ['AWS_ACCESS_KEY_ID']
AWS_SECRET_ACCESS_KEY = os.environ['AWS_SECRET_ACCESS_KEY']
AWS_REGION = os.environ['AWS_REGION']

AWS_KAFKA_INVENTORY_GROUP = os.environ['AWS_KAFKA_INVENTORY_GROUP']

MIRRORED_INSTANCES_ERR_MSG = "By convention there should not be presented to " \
                             "instances with same inventory gorup and name"

INSTANCE_DOES_NOT_EXISTS_ERR_MSG = "There is no running instance with {0} tag name and {1} inventory group"


class AWSEC2Exception(Exception):
    pass


class KafkaClusterException(Exception):
    pass


class AWSConnection(object):
    def __init__(self, aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                 region_name=AWS_REGION):

        self.ec2conn = ec2.connect_to_region(aws_access_key_id=aws_access_key_id,
                                             aws_secret_access_key=aws_secret_access_key,
                                             region_name=region_name)

    def search_instances(self, filters):
        default_filters = {"instance-state-name": "running"}
        default_filters.update(filters)

        reservations = self.ec2conn.get_all_instances(filters=filters)

        return [i for r in reservations for i in r.instances]

    def get_instance(self, inventory_group, name):
        filters = {"tag:Name": name,
                   "tag:inventory_group": inventory_group}

        found_instances = self.search_instances(filters)

        if len(found_instances) > 1:
            raise AWSEC2Exception(MIRRORED_INSTANCES_ERR_MSG)

        return found_instances

    def get_instances_by_inventory_gorup(self, inventory_group):
        filters = {"tag:inventory_group": inventory_group}

        return self.search_instances(filters)


class KafkaCluster(object):
    def __init__(self, aws_hosts_file_path, metavars_path, inventory_group):
        self.inventory_group = inventory_group
        self.metavars = collections.defaultdict(dict)
        self.ec2conn = AWSConnection()
        self.cluster_descriptor = self.get_aws_instances_description(aws_hosts_file_path)
        self.read_old_meta(metavars_path)

        self.update_metavars()

    @staticmethod
    def open_yaml(path):
        with open(path) as f:
            config = yaml.safe_load(f)

        return config

    def get_aws_instances_description(self, path):
        return self.open_yaml(path)['aws']['instances']

    def read_old_meta(self, metavars_file_path):
        if os.path.exists(metavars_file_path) and os.path.isfile(metavars_file_path):
            old_meta = self.read_metavars_file()

            # update old_meta
            self.metavars.update(old_meta)

    def update_metavars(self):
        for instance_descriptor in self.cluster_descriptor:
            instances = self.ec2conn.get_instance(instance_descriptor['inventory_group'], instance_descriptor['name'])

            if not instances:
                self.delete_instance(instance_descriptor['name'])
                continue

            instance = instances[0]

            if instance.tags['Name'] not in self.metavars[instance_descriptor['inventory_group']]:
                self.metavars[instance_descriptor['inventory_group']].\
                    update({str(instance.tags['Name']): {"broker_id": "", "ip_addr": str(instance.private_ip_address)}})

        self.generate_broker_ids()

        self.write_metavars_file()

    def read_metavars_file(self):
        return self.open_yaml(METAVARS_PATH)['metavars']

    def write_metavars_file(self):
        write_meta = {}
        write_meta.update({"metavars": self.metavars})

        with open(METAVARS_PATH, 'w') as outfile:
            outfile.write(yaml.dump(write_meta, default_flow_style=True))

    def generate_broker_ids(self):
        curr_id = 1  # Do NOT put 0 here
        old_ids = []

        for tag_Name, descriptor in self.metavars[self.inventory_group].iteritems():
            def get_new_id(list_ids, c_id):
                new_id = copy.copy(c_id)

                while new_id in list_ids:
                    new_id += 1

                return new_id

            if descriptor['broker_id']:
                old_ids.append(descriptor['broker_id'])
            else:
                n_id = get_new_id(old_ids, curr_id)
                descriptor['broker_id'] = n_id
                self.metavars[self.inventory_group].update({tag_Name: descriptor})
                curr_id += 1

        self.write_metavars_file()

    def add_node(self, name):
        print("Node {0} was added to {1} cluster.".format(name, self.inventory_group))

    def delete_instance(self, name):
        if name in self.metavars[self.inventory_group]:
            self.metavars[self.inventory_group].pop(name, None)
            self.write_metavars_file()
            print("Node {0} in cluster {1} was deleted from metavars.".format(name, self.inventory_group))

    def delete_cluster(self):
        if self.inventory_group in self.metavars:
            self.metavars.pop(self.inventory_group, None)
            self.write_metavars_file()
            print("Cluster {0} was deleted from metavars.".format(self.inventory_group))

if __name__ == "__main__":
    yaml.add_representer(collections.defaultdict, Representer.represent_dict)
    cluster = KafkaCluster(AWS_HOSTS_FILE_PATH, METAVARS_PATH, AWS_KAFKA_INVENTORY_GROUP)

    parser = argparse.ArgumentParser(description='Parser of kafka operations')
    parser.add_argument('--add-node', action='store_const', const=lambda: cluster.add_node("NAME!!!"), dest='cmd')
    parser.add_argument('--delete-node', action='store_const', const=lambda: cluster.delete_instance("NAME!!!"), dest='cmd')
    parser.add_argument('--delete-cluster', action='store_const', const=lambda: cluster.delete_cluster(), dest='cmd')

    args = parser.parse_args()

    if args.cmd is not None:
        args.cmd()
