#!/bin/bash

echo 'Destroying CDK application...'
cd ./shadowstar_api/infrastructure/
cdk destroy --all
cd ../../
echo 'Done'
