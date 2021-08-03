#!/bin/bash

echo 'Deploying CDK application...'
cd ./shadowstar_api/infrastructure/
cdk deploy --all
cd ../../

# Chalice exposes the EndpointURL as the final (4th) CloudFormation stack output
API_BASE=$(aws cloudformation describe-stacks --stack-name shadowstar-api | jq -r '.Stacks[].Outputs[3].OutputValue')

# Our S3 hosting stack only has one output, the bucket name
BUCKET_NAME=$(aws cloudformation describe-stacks --stack-name shadowstar-webapp | jq -r '.Stacks[].Outputs[0].OutputValue')

echo 'Deploying web app to S3...'
cat ./shadowstar_webapp/template/index.html | sed "s,%API_BASE%,$API_BASE,g" > ./shadowstar_webapp/index.html
aws s3 cp ./shadowstar_webapp/index.html s3://$BUCKET_NAME/

echo -e "\n\nhttps://$BUCKET_NAME.s3.amazonaws.com/index.html"
