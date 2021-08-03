import re
import os
import json

import boto3


from chalice import Chalice, Rate
from chalice.app import BadRequestError


app = Chalice(app_name='shadowstar_api')
app.debug = True

S3_BUCKET_RE = re.compile(r's3://(.*?)/(.*)')
VALID_SOURCES = [
    '%', 'afrinic', 'apnic', 'arin', 'lacnic', 'ripe', 'level3', 'nttcom', 
    'radb', 'tc', 'reach', 'wcgdb', 'jpirr'
]

ATHENA_BUCKET = os.environ.get('ATHENA_BUCKET')
ATHENA_TABLE = os.environ.get('ATHENA_TABLE')
ATHENA_DATABASE = os.environ.get('ATHENA_DATABASE')
VPC_DEFAULT_SG = os.environ.get('VPC_DEFAULT_SG')
VPC_DEFAULT_SUBNET = os.environ.get('VPC_DEFAULT_SUBNET')
ECS_CLUSTER_NAME = os.environ.get('ECS_CLUSTER_NAME')
ECS_TASK_DEFINITION = os.environ.get('ECS_TASK_DEFINITION')

SQL_SOURCE_CLAUSE = "LOWER(source) LIKE '%s'"
SQL_SELECT_BLOCKS = '''
SELECT * FROM %s WHERE 
    (%s) AND
    (LOWER(netname) LIKE '%s' OR LOWER(description) LIKE '%s' OR LOWER(maintained_by) LIKE '%s');
'''.replace('\n', ' ').replace('\t', ' ')


@app.schedule(Rate(7, unit=Rate.DAYS))
def schedule_auto_update(event):
    s3 = boto3.client('s3')
    ecs = boto3.client('ecs')
    # Check for existing update jobs
    res = ecs.list_tasks(cluster=ECS_CLUSTER_NAME)
    if len(res['taskArns']) == 0:
        # Run the database update
        ecs.run_task(
            cluster=ECS_CLUSTER_NAME,
            launchType='FARGATE',
            taskDefinition=ECS_TASK_DEFINITION,
            networkConfiguration={
                'awsvpcConfiguration': {
                    'subnets': [
                        VPC_DEFAULT_SUBNET,
                    ],
                    'securityGroups': [
                        VPC_DEFAULT_SG
                    ],
                    'assignPublicIp': 'ENABLED'
                }
            }
        )
    # Purge the results from bucket so as not to grow forever
    res = s3.list_objects(Bucket=ATHENA_BUCKET, Prefix='results/')
    for key in res['Contents']:
        s3.delete_object(Bucket=ATHENA_BUCKET, Key=key['Key'])


@app.route('/refresh-db', methods=['POST'], cors=True)
def refresh_db():
    ecs = boto3.client('ecs')
    res = ecs.list_tasks(cluster=ECS_CLUSTER_NAME)
    if len(res['taskArns']) != 0:
        raise BadRequestError('Update job already running')
    ecs.run_task(
        cluster=ECS_CLUSTER_NAME,
        launchType='FARGATE',
        taskDefinition=ECS_TASK_DEFINITION,
        networkConfiguration={
            'awsvpcConfiguration': {
                'subnets': [
                    VPC_DEFAULT_SUBNET,
                ],
                'securityGroups': [
                    VPC_DEFAULT_SG
                ],
                'assignPublicIp': 'ENABLED'
            }
        }
    )


@app.route('/metadata', methods=['GET'], cors=True)
def metadata():
    s3 = boto3.client('s3')
    try:
        res = s3.get_object(Bucket=ATHENA_BUCKET, Key='metadata/metadata.json')
        return res['Body'].read()
    except:
        return json.dumps({
            'system_version': None,
            'num_network_blocks': None,
            'last_updated': None
        })


@app.route('/query', methods=['POST'], cors=True)
def query():
    if any([req in [None, ''] for req in [ATHENA_BUCKET, ATHENA_TABLE, ATHENA_DATABASE]]):
        raise BadRequestError('Environment variables are not set')

    if 'keyword' not in app.current_request.json_body:
        raise BadRequestError('"keyword" body parameter not found')

    # Sources are a list of sources to search against
    if 'sources' in app.current_request.json_body:
        sources = list(app.current_request.json_body['sources'])
        if any([source not in VALID_SOURCES for source in sources]):
            raise BadRequestError('"sources" body parameter contains an invalid source')
    else:
        # Default source list matches everything
        sources = ['%']

    keyword = str(app.current_request.json_body['keyword']).lower()
    source_clause = ' OR '.join([SQL_SOURCE_CLAUSE % source for source in sources])
    query = SQL_SELECT_BLOCKS % (ATHENA_TABLE, source_clause, keyword, keyword, keyword)

    athena = boto3.client('athena')
    qexec = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={
            'Database': ATHENA_DATABASE
        },
        ResultConfiguration={
            'OutputLocation': 's3://%s/results' % ATHENA_BUCKET
        }
    )

    exec_id = qexec['QueryExecutionId']
    if exec_id is not None:
        return json.dumps({"execution_id": exec_id, "query": query})
    else:
        raise BadRequestError('Failed to execute Athena query')


@app.route('/retrieve/{execution_id}', methods=['GET'], cors=True)
def retrieve(execution_id):
    if execution_id in ['', None]:
        raise BadRequestError('Missing execution_id parameter')
    
    athena = boto3.client('athena')
    s3 = boto3.client('s3')

    res = athena.get_query_execution(QueryExecutionId=execution_id)
    path = res['QueryExecution']['ResultConfiguration']['OutputLocation']
    matches = S3_BUCKET_RE.findall(path)

    if len(matches) != 1:
        raise BadRequestError('Could not parse Athena results')

    bucket_name = matches[0][0]
    key_path = matches[0][1]
    url = s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket_name, 'Key': key_path}
    )

    return json.dumps({"results": url})
