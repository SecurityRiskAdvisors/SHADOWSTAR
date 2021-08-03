#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# TODO: Make this more memory conservative 

import os
import re
import csv
import json
import gzip
import time
import os.path
import logging
import argparse
import subprocess as sp

from datetime import datetime

import boto3

from netaddr import iprange_to_cidrs
from irrd.rpsl.rpsl_objects import rpsl_object_from_text


# Optional ARIN configuration
ARIN_API_KEY = os.environ.get('ARIN_API_KEY')
ARIN_SECRET_NAME = os.environ.get('ARIN_SECRET_NAME')

# Optional S3 configuration
S3_BUCKET = os.environ.get('S3_BUCKET')
S3_PATH = os.environ.get('S3_PATH')
S3_METADATA_PATH = os.environ.get('S3_METADATA_PATH')
SYSTEM_VERSION = os.environ.get('SYSTEM_VERSION')


TOTAL_BLOCK_COUNT = 0
ARIN_ORGS = {}
CURRENT_FILENAME = "empty"
VERSION = '2.0'

FILELIST = [
    'arin_db.txt',

    'afrinic.db.gz',

    'apnic.db.inet6num.gz',
    'apnic.db.inetnum.gz',
    'apnic.db.route-set.gz',
    'apnic.db.route.gz',
    'apnic.db.route6.gz',

    'lacnic.db.gz', 
    'lacnic_irr.db.gz',

    'ripe.db.inetnum.gz', 
    'ripe.db.inet6num.gz',
    'ripe.db.route-set.gz',
    'ripe.db.route.gz',
    'ripe.db.route6.gz',

    'arin.db.gz',
    'arin-nonauth.db.gz',
    'level3.db.gz',
    'nttcom.db.gz',
    'radb.db.gz',
    'tc.db.gz',
    'reach.db.gz',
    'wcgdb.db.gz',
    'jpirr.db.gz'
]

# Setup logging configuration for task
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger('shadowstar_db_parser')


def get_source(filename: str):
    if filename.startswith('afrinic'):
        return b'afrinic'
    elif filename.startswith('apnic'):
        return b'apnic'
    elif filename.startswith('arin'):
        return b'arin'
    elif filename.startswith('lacnic'):
        return b'lacnic'
    elif filename.startswith('ripe'):
        return b'ripe'
    elif filename.startswith('level3'):
        return b'level3'
    elif filename.startswith('nttcom'):
        return b'nttcom'
    elif filename.startswith('radb'):
        return b'radb'
    elif filename.startswith('tc'):
        return b'tc'
    elif filename.startswith('reach'):
        return b'reach'
    elif filename.startswith('wcgdb'):
        return b'wcgdb'
    elif filename.startswith('jpirr'):
        return b'jpirr'
    else:
        logger.error(f"Can not determine source for {filename}")
    return None


def parse_property(block: str, name: str) -> str:
    match = re.findall('^%s:\s?(.+)$' % (name), block, re.MULTILINE)
    if match:
        # remove empty lines and remove multiple names
        x = ' '.join(list(filter(None, (x.strip().replace(
            "%s: " % name, '').replace("%s: " % name, '') for x in match))))
        # remove multiple whitespaces by using a split hack
        # decode to latin-1 so it can be inserted in the database
        return ' '.join(x.split())
    else:
        return None


def parse_arin_inetnum(block: str) -> str:
    # ARIN WHOIS IPv4
    match = re.findall(r'^NetRange:[\s]*((?:\d{1,3}\.){3}\d{1,3})[\s]*-[\s]*((?:\d{1,3}\.){3}\d{1,3})', block, re.MULTILINE)
    if match:
        ip_start = match[0][0]
        ip_end = match[0][1]
        return f"{ip_start}-{ip_end}"
    # ARIN WHOIS IPv6
    match = re.findall(r'^NetRange:[\s]*([0-9a-fA-F:\/]{1,43})[\s]*-[\s]*([0-9a-fA-F:\/]{1,43})', block, re.MULTILINE)
    if match:
        ip_start = match[0][0]
        ip_end = match[0][1]
        return f"{ip_start}-{ip_end}"
    logger.warning(f"Could not parse ARIN block {block}")
    return None


def read_blocks(filename: str) -> list:
    if filename.endswith('.gz'):
        openmethod = gzip.open
    else:
        openmethod = open

    # inetnum, inet6num, route, route-set, route6
    rpsl_block_re = re.compile(r'^(inet|route).{0,5}:')
    cust_source = get_source(filename.split('/')[-1])
    single_block = b''
    blocks = []

    # APNIC/LACNIC/RIPE/AFRINIC/IRR are all in RPSL
    def is_rpsl_block_start(line: bytes):
        line_str = line.decode('utf-8', 'ignore')
        if rpsl_block_re.match(line_str):
            return True
        return False

    # ARIN's WHOIS database is in a custom format
    def is_arin_block_start(line):
        if line.startswith(b'NetHandle:'):
            return True
        elif line.startswith(b'V6NetHandle:'):
            return True
        elif line.startswith(b'OrgID:'):
            return True
        return False

    with openmethod(filename, mode='rb') as f:
        for line in f:
            # skip comments
            if line.startswith(b'%') or line.startswith(b'#'):
                continue
            # block end
            if line.strip() == b'':
                if is_rpsl_block_start(single_block) or is_arin_block_start(single_block):
                    # add source
                    single_block += b"cust_source: %s" % (cust_source)
                    blocks.append(single_block)
                    if len(blocks) % 1000 == 0:
                        logger.debug(f"parsed another 1000 blocks ({len(blocks)} so far)")
                    single_block = b''
                else:
                    single_block = b''
            else:
                single_block += line
    
    logger.info(f"Got {len(blocks)} blocks")
    return blocks


def range_to_cidr(inetnum):
    match = re.findall(r'((?:\d{1,3}\.){3}\d{1,3})[\s]*-[\s]*((?:\d{1,3}\.){3}\d{1,3})', inetnum, re.MULTILINE)
    if match:
        # netaddr can only handle strings, not bytes
        ip_start = match[0][0]
        ip_end = match[0][1]
        return iprange_to_cidrs(ip_start, ip_end)
    else:
        return inetnum


def parse_blocks(blocks, csv_writer):
    global TOTAL_BLOCK_COUNT
    arin_customer_re = re.compile('^OrgID:')
    arin_network_re = re.compile('^(Net|V6Net)Handle:')

    for block in blocks:
        # The RPSL parser works on str not bytes
        b = block.decode('utf-8', 'ignore') 

        inetnum = ''
        netname = ''
        description = ''
        country = ''
        maintained_by = ''
        created = ''
        last_modified = ''
        source = ''

        # ARIN has an Organization object which you have to parse out in order
        # to get any details about network blocks
        #if is_arin_customer(b):
        if arin_customer_re.match(b):
            orgid = parse_property(b, 'OrgID')
            orgname = parse_property(b, 'OrgName')
            country = parse_property(b, 'Country')
            ARIN_ORGS[orgid] = (orgname, country)
            continue

        # ARIN's dump format is also not in RPSL for whatever reason. They
        # decided to make their own custom format.
        #elif is_arin_network(b):
        elif arin_network_re.match(b):
            inetnum = parse_arin_inetnum(b)
            orgid = parse_property(b, 'OrgID')
            netname = parse_property(b, 'NetName')
            description = parse_property(b, 'NetHandle')
            # ARIN IPv6
            if not description:
                description = parse_property(b, 'V6NetHandle')
            country = ARIN_ORGS[orgid][1]
            maintained_by = ARIN_ORGS[orgid][0]
            created = parse_property(b, 'RegDate')
            last_modified = parse_property(b, 'Updated')
            source = parse_property(b, 'cust_source')

        # All other data dumps are in RPSL so we can use a proper parser
        # provided by the irrd package
        else:
            try:
                rpsl_object = rpsl_object_from_text(b)
                
                # We treat any of these RPSL objects as "inetnum" objects.
                inetnum_properties = ['inetnum', 'inet6num', 'route', 'route6']
                for prop in inetnum_properties:
                    if prop in rpsl_object.parsed_data:
                        inetnum = rpsl_object.parsed_data[prop]
                        break

                # NOTE: This is a special edge case for a route-set; multiple
                # records have to be created from this single RPSL object.
                if 'route-set' in rpsl_object.parsed_data:
                    netname = rpsl_object.parsed_data['route-set']
                    # Changes type from str -> list
                    if 'members' in rpsl_object.parsed_data:
                        inetnum = rpsl_object.parsed_data['members']

                # Some of these might exist, or not, depends entirely on RIR/IRR
                if 'netname' in rpsl_object.parsed_data:
                    netname = rpsl_object.parsed_data['netname']
                if 'descr' in rpsl_object.parsed_data:
                    description = ' '.join(rpsl_object.parsed_data['descr'])
                if 'country' in rpsl_object.parsed_data:
                    country = ' '.join(rpsl_object.parsed_data['country'])
                if 'mnt-by' in rpsl_object.parsed_data:
                    maintained_by = ' '.join(rpsl_object.parsed_data['mnt-by'])
                if 'last-modified' in rpsl_object.parsed_data:
                    last_modified = ' '.join(rpsl_object.parsed_data['last-modified'])
                if 'changed' in rpsl_object.parsed_data:
                    last_modified = ' '.join(rpsl_object.parsed_data['changed'])
                if 'created' in rpsl_object.parsed_data:
                    created = ' '.join(rpsl_object.parsed_data['created'])
                
                # Source is special, we should always have a source value 
                if 'source' in rpsl_object.parsed_data:
                    source = rpsl_object.parsed_data['source']
                else:
                    source = parse_property(b, 'cust_source')
            except Exception as ex:
                logger.error(ex)

        # See the above note regarding the route-set RPSL object
        if isinstance(inetnum, list):
            for cidr in inetnum:
                c = re.sub(r'[^0-9a-fA-F\:\.\/]', '', str(cidr))
                row = [c, netname, description, country, maintained_by, created, last_modified, source]
                csv_writer.writerow(row)
            TOTAL_BLOCK_COUNT += len(inetnum)
        else:
            c = range_to_cidr(inetnum)
            if isinstance(c, list):
                for sub in c:
                    s = re.sub(r'[^0-9a-fA-F\:\.\/]', '', str(sub))
                    row = [s, netname, description, country, maintained_by, created, last_modified, source]
                    csv_writer.writerow(row)
                TOTAL_BLOCK_COUNT += len(c)
            else:
                    s = re.sub(r'[^0-9a-fA-F\:\.\/]', '', str(c))
                    row = [s, netname, description, country, maintained_by, created, last_modified, source]
                    csv_writer.writerow(row)
                    TOTAL_BLOCK_COUNT += 1


def main(output_file):
    overall_start_time = time.time()

    with open(output_file, 'w') as output_file_handle:
        csv_writer = csv.writer(output_file_handle, delimiter='\t', quoting=csv.QUOTE_MINIMAL)
        for entry in FILELIST:
            global CURRENT_FILENAME
            CURRENT_FILENAME = entry
            f_name = f"./databases/{entry}"

            if os.path.exists(f_name):
                logger.info(f"parsing database file: {f_name}")
                start_time = time.time()
                blocks = read_blocks(f_name)
                logger.info(f"database parsing finished: {round(time.time() - start_time, 2)} seconds")
                logger.info('parsing blocks')
                start_time = time.time()
                parse_blocks(blocks, csv_writer)
                logger.info(f"block parsing finished: {round(time.time() - start_time, 2)} seconds")
                del blocks
            else:
                logger.info(f"File {f_name} not found. Please download using download_dumps.sh")

            # "Free" the memory associated with the large dictionary since it is
            # exclusive to ARIN's WHOIS database dump.
            if entry == 'arin_db.txt':
                del globals()['ARIN_ORGS']

    CURRENT_FILENAME = "empty"
    logger.info(f"script finished: {round(time.time() - overall_start_time, 2)} seconds")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parse WHOIS databases into single TSV file')
    parser.add_argument('-d', action="store_true", dest='download_dumps')
    parser.add_argument('-o', dest='output_file', type=str, required=True, help="Output TSV file")
    parser.add_argument('--debug', action="store_true", help="set loglevel to DEBUG")
    parser.add_argument('--version', action='version', version=f"%(prog)s {VERSION}")
    args = parser.parse_args()
    secret_arin_api_key = None

    # If there is no ARIN key defined, check Secrets Manager and export as environment key
    if ARIN_API_KEY in ['', None] and ARIN_SECRET_NAME not in ['', None]:
        secretsmanager = boto3.client('secretsmanager')
        response = secretsmanager.get_secret_value(SecretId=ARIN_SECRET_NAME)
        secret_arin_api_key = response['SecretString']

    # Enable debugging
    if args.debug:
        logger.setLevel(logging.DEBUG)

    # Include ARIN API key as needed
    if args.download_dumps:
        env = os.environ.copy()
        if secret_arin_api_key not in [None, '', 'NONE']:
            env['ARIN_API_KEY'] = secret_arin_api_key
        sp.run('bash ./download_dumps.sh', env=env, shell=True)

    # Run default script to generate TSV file
    main(args.output_file)

    # Upload the files to S3 if we need to
    if not any([req in ['', None] for req in [S3_BUCKET, S3_PATH]]):
        logger.info('Found S3 configuration, uploading to desired path')
        s3 = boto3.client('s3')
        s3.upload_file(args.output_file, S3_BUCKET, S3_PATH)

    # Update metadata if we need to
    if not any([req in ['', None] for req in [S3_BUCKET, S3_METADATA_PATH]]):
        logger.info('Found S3 configuration, uploading metadata desired path')
        s3 = boto3.client('s3')
        with open('metadata.json', 'w') as handle:
            handle.write(json.dumps({
                'system_version': SYSTEM_VERSION,
                'num_network_blocks': TOTAL_BLOCK_COUNT,
                'last_update': datetime.now().isoformat()
            }))
        s3.upload_file('metadata.json', S3_BUCKET, S3_METADATA_PATH)
