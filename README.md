# SHADOWSTAR - Internet Registry Shadowing Service

## Contents

- [Introduction](#introduction)
- [Quickstart](#quickstart)
- [SHADOWSTAR Architecture](#shadowstar-architecture)
- [Pre-requisites and Setup](#pre-requisites-and-setup)
- [Uninstalling/removing](#uninstallingremoving)
- [Troubleshooting](#troubleshooting)
- [Credits](#credits)

## Introduction

SHADOWSTAR is a [Regional Internet Registry
(RIR)](https://en.wikipedia.org/wiki/Regional_Internet_registry) and [Internet
Routing Registry (IRR)](https://en.wikipedia.org/wiki/Internet_Routing_Registry)
shadowing service. The tool collects public/private data dumps, parses them into
a single unified data model, and provides a search interface for performing
SQL-based queries.

In it's full form, it is a serverless AWS application, with simple auto-updating
capabilities to keep RIR/IRR data fresh. The tool can also be used by single
users in a simpler capacity as described in the [Quickstart](#quickstart)
section.

The goal of SHADOWSTAR is to provide the best possible interface for discovering
network blocks that belong to an organization. The primary use case of the tool
is locating targets for penetration tests and Red Team operations.

This repository contains the SHADOWSTAR AWS application. There are three parts:

1. `shadowstar_api` is a [Chalice](https://aws.github.io/chalice/index.html) and
   [CDK](https://aws.amazon.com/cdk/) application that creates the
   infrastructure needed to host the auto-updating service and the REST API for
   search queries.

2. `shadowstar_db_parser` is a parsing utility that can consume data dumps in
   RPSL and ARIN's data format. It is used to unify the data model of the
   disparate data dumps into a single TSV file.

3. `shadowstar_webapp` is a simple single page web application that interacts
   with the REST API; it provides a nicer user interface to perform searches.

## Quickstart

Don't want to setup the AWS application? Have a powerful workstation? You can
run `shadowstar_db_parser` locally to create a `grep` friendly TSV file that
works well for single users:

```
cd shadowstar_db_parser
pip3 install -r requirements.txt
python3 parser.py -d -o network_info.tsv
grep '.*google.*' network_info.tsv | python3 cidr_reduce.py
```

The `parser.py` script will begin a long and memory intensive process; the
number of network blocks collected with the default configuration is
approximately 11 million. You can modify the `download_dumps.sh` script to
control which data dumps you consume.

At peak memory load, the ARIN/RIPE databases take about 6 GB of memory to hold.
In a future release, this will be done in chunks in an effort to be more
conservative at peak memory load at the cost of some runtime performance. In the
interim, you are responsible for having a sufficiently powerful machine.

**NOTE**: The `cidr_reduce.py` script performs a reduction on the CIDR blocks
collected via a keyword search. It produces the minimal set of CIDR blocks which
span the same logical range as the original results. It is highly recommended
that you use the script to clean up results.

## SHADOWSTAR Architecture

The SHADOWSTAR architecture is VPC-based; it follows a reference architecture
design popularized by AWS:
https://docs.aws.amazon.com/codebuild/latest/userguide/cloudformation-vpc-template.html

Inside the VPC, there is an ECS cluster that serves as the computational
resource used to implement auto-updating via a Fargate task.

Aside from the VPC, there are two S3 buckets, one used to hold the TSV file
created by the `shadowstar_db_parser` and the other to host the web app.

Finally, there is an AWS Glue database/table which is setup to target the S3
bucket holding the TSV file. This allows us to use the AWS Athena service to
perform SQL queries against the TSV data.

## Pre-requisites and Setup

To get the most out of the SHADOWSTAR tool you should obtain an API key for
[ARIN's bulk WHOIS API](https://www.arin.net/reference/research/bulkwhois/);
otherwise, you will be missing millions of potential network blocks.

Currently the tool requires admin (ie.
`arn:aws:iam::aws:policy/AdministratorAccess`) rights to deploy. In a future
release, the deployment will run within the confines of a pre-defined IAM role.

1. First, install the `aws-cdk` package from NPM:

```
sudo npm install -g aws-cdk
```

2. Next, create an ARIN API key in Secrets Manager; if you don't have a valid
   API key, create an entry with the default value of `"NONE"`, otherwise enter
   your key here instead of the default:

```
aws secretsmanager create-secret --name ShadowStarARINAPIKey --secret-string "NONE"
```

3. Fill out the values in the `deploy.sample.json` file to have the output
   values from the command you just ran; along with a selection for an ingress
   CIDR block--this is used to control access to the web app. Finally, rename
   the file to `deploy.json`

```
vim deploy.sample.json
mv deploy.sample.json deploy.json
```

4. Install the Python dependencies; you *really should* create a virtual
   environment:

```
python3 -m venv venv
. venv/bin/activate
pip3 install -r requirements.txt
```

5. If this is you're first time using the CDK you'll need to bootstrap your
   environment:

```
cd shadowstar_api/infrastructure/ && cdk bootstrap
```

6. Now you can finally run the `deploy.sh` script which runs the `cdk deploy`
   command for you to deploy the entire application:

```
./deploy.sh
```

7. Once you have deployed the application, go to the S3 URL at the bottom of
   output. Click on the 'About' button in the top-right corner, then click the
   'Force DB Update' button. This will cause a database update task to start;
   the task will take about 90 minutes to complete. Once it finishes, you're
   ready to go. All subsequent updates will be performed automatically every 7
   days.

## Uninstalling/removing

Just run the `destroy.sh` script. See the troubleshooting section if you have
issues with deleting the VPC.

## Troubleshooting

- If you have problems installing the `irrd` package, you may need to install a
  specific version of the `python3-dev` package ex: `python3.8-dev`

- If you have the `amazon-ecr-credential-helper` installed, you need to
  temporarily remove the `~/.docker/config.json` file in order for the
  `deploy.sh` script to work.

- There is sometimes an issue with deleting the VPC component of the
  infrastructure, if you have that problem, go to the VPC console, find the
  SHADOWSTAR VPC and manually delete it, then re-run `destroy.sh`

## Credits

1. This project was originally inspired by `network_info` project here:
	- https://github.com/firefart/network_info
2. This project also makes use of the `irrd` package for RPSL parsing:
	- https://github.com/irrdnet/irrd
3. Finally thanks to Evan Perotti from SRA for answering all my dumb questions about AWS

