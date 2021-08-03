#!/usr/bin/env python3

import os
import json

from aws_cdk import core as cdk
from stacks.chaliceapp import ChaliceApp
from stacks.webapp import WebApp


SYSTEM_VERSION = '1.0.0'


# Load in SHADOWSTAR deployment config
if not os.path.exists('../../deploy.json'):
  print('You have not yet configured the tool for deployment')
  exit(1)

with open('../../deploy.json', 'r') as handle:
  config = json.loads(handle.read())

# Update Chalice resource policy to restrict the API access
with open('../runtime/.chalice/resource-policy.json', 'r') as handle:
  policy = json.loads(handle.read())
  policy['Statement'][0]['Condition']['IpAddress']['aws:SourceIp'][0] = config['ingress_cidr_block']

with open('../runtime/.chalice/resource-policy.json', 'w') as handle:
  handle.write(json.dumps(policy))


app = cdk.App()

# Create a stack for the Chalice app + supporting infra
chalice_app = ChaliceApp(
  app,
  'shadowstar-api',
  config['arin_secret_name'],
  config['arin_secret_arn'],
  SYSTEM_VERSION
)

# Create a stack for S3 hosted web app
web_app = WebApp(
  app,
  'shadowstar-webapp',
  config['ingress_cidr_block']
)

# Synthesize and deploy
app.synth()
