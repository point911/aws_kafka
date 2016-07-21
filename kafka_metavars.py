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

INSTANCE_DOES_NOT_EXISTS_ERR_MSG = "There is no running instance with {0} tag name and {1} inventory group"


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
            self.metavars = self.read_metavars_file()

            # print old_meta
            meta.update(self.metavars)

        for instance in self.aws_instances:
            reservations = self.ec2conn.get_all_instances(filters={"tag:Name": instance['name'],
                                                                   "tag:inventory_group": instance['inventory_group'],
                                                                   "instance-state-name": "running"})

            found_instances = [i for r in reservations for i in r.instances]

            if len(found_instances) > 1:
                raise KafkaClusterException(MIRRORED_INSTANCES_ERR_MSG)

            if len(found_instances) == 0:
                raise KafkaClusterException(INSTANCE_DOES_NOT_EXISTS_ERR_MSG.format(instance['name'], instance['inventory_group']))

            if str(found_instances[0].private_ip_address) not in meta[instance['inventory_group']]:
                meta[instance['inventory_group']].update({str(found_instances[0].private_ip_address): {"broker_id": ""}})

        self.write_metavars_file(meta)

        return meta

    def read_metavars_file(self):
        return self.open_yaml(METAVARS_PATH)['metavars']

    @staticmethod
    def write_metavars_file(meta):
        write_meta = {}
        write_meta.update({"metavars": meta})

        with open(METAVARS_PATH, 'w') as outfile:
            outfile.write(yaml.dump(write_meta, default_flow_style=True))

    def generate_broker_ids(self):
        for group, ips in self.metavars.iteritems():
            max_id = 22
            for ip, ip_meta in ips.iteritems():

                if ip_meta['broker_id']:
                    if max_id < int(ip_meta['broker_id']):
                        max_id = int(ip_meta['broker_id'])
                else:
                    ip_meta['broker_id'] = max_id
                    self.metavars[group].update({ip: ip_meta})
                    max_id += 1

        self.write_metavars_file(self.metavars)

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




