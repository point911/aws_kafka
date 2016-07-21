#!/usr/bin/env python

import os
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

MIRRORED_INSTANCES_ERR_MSG = "By convention there should not be presented to " \
                             "instances with same inventory gorup and name"


class KafkaClusterException(Exception):
    pass


class KafkaCluster(object):
    def __init__(self):
        self.ec2conn = ec2.connect_to_region(aws_access_key_id=AWS_ACCESS_KEY_ID,
                                             aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                                             region_name=AWS_REGION)
        self.aws_instances = self.get_aws_instances_description(AWS_HOSTS_FILE_PATH)

        self.metavars = self.update_metavars()

    @staticmethod
    def open_yaml(path):
        with open(path) as f:
            config = yaml.safe_load(f)

        return config

    def get_aws_instances_description(self, path):
        return self.open_yaml(path)['aws']['instances']

    def update_metavars(self):
        meta = collections.defaultdict(dict)

        if os.path.exists(METAVARS_PATH) and os.path.isfile(METAVARS_PATH):
            old_meta = self.read_metavars_file()

            # print old_meta
            meta.update(old_meta)

        for instance in self.aws_instances:
            # print("*"*20)
            # print(instance['name'])
            # print(instance['inventory_group'])
            reservations = self.ec2conn.get_all_instances(filters={"tag:Name": instance['name'],
                                                                   "tag:inventory_group": instance['inventory_group']})

            found_instances = [i for r in reservations for i in r.instances]

            if len(found_instances) > 1:
                raise KafkaClusterException(MIRRORED_INSTANCES_ERR_MSG)

            # print(found_instances[0].private_ip_address)


            if str(found_instances[0].private_ip_address) not in meta[instance['inventory_group']]:
                meta[instance['inventory_group']].update({str(found_instances[0].private_ip_address): {"broker_id": ""}})

        self.write_metavars_file(meta)

        return meta

    def read_metavars_file(self):
        return self.open_yaml(METAVARS_PATH)

    @staticmethod
    def write_metavars_file(meta):
        with open(METAVARS_PATH, 'w') as outfile:
            outfile.write(yaml.dump(meta, default_flow_style=True))

    def generate_broker_ids(self):
        ids_info = collections.defaultdict(list)



        for instance in self.aws_instances:
            # print(self.metavars[instance['inventory_group']])

            group_broker_list = self.metavars[instance['inventory_group']].values()
            # print group_broker_list
            [ids_info[instance['inventory_group']].append(broker['broker_id']) for broker in group_broker_list if 'broker_id' in broker]

        # for ids_list in ids_info.values():
        #     for br_id

        # print(ids_info)

    def add_nodes(self):
        self.generate_broker_ids()
        print("Nodes were added.")

    def delete_nodes(self):
        print("Nodes were deleted.")


if __name__ == "__main__":
    yaml.add_representer(collections.defaultdict, Representer.represent_dict)
    cluster = KafkaCluster()

    parser = argparse.ArgumentParser(description='Parser of kafka operations')
    parser.add_argument('--add-nodes', action='store_const', const=lambda: cluster.add_nodes(), dest='cmd')
    parser.add_argument('--delete-nodes', action='store_const', const=lambda: cluster.delete_nodes(), dest='cmd')

    args = parser.parse_args()

    if args.cmd is not None:
        args.cmd()




