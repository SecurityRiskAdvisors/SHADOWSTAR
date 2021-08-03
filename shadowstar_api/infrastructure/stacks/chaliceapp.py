import os

from chalice.cdk import Chalice

from aws_cdk import (
    aws_glue as glue,
    aws_logs as logs,
    aws_s3 as s3,
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    core as cdk
)


RUNTIME_SOURCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), os.pardir, 'runtime')


class ChaliceApp(cdk.Stack):

    def __init__(self, scope, id, arin_secret_name, arin_secret_arn, system_version, **kwargs):
        super().__init__(scope, id, **kwargs)
        self.arin_secret_name = arin_secret_name
        self.arin_secret_arn = arin_secret_arn
        self.system_version = system_version
        self._create_athena_s3_bucket()
        self._create_athena_database()
        self._create_fargate_cluster()
        self._create_fargate_task()
        self.chalice = Chalice(
            self,
            'ChaliceApp',
            source_dir=RUNTIME_SOURCE_DIR,
            stage_config={
                'environment_variables': {
                    'ATHENA_BUCKET': self.athena_bucket.bucket_name,
                    'ATHENA_TABLE': self.athena_table.table_input.name,
                    'ATHENA_DATABASE': self.athena_database.database_name,
                    'VPC_DEFAULT_SG': self.vpc.vpc_default_security_group,
                    'VPC_DEFAULT_SUBNET': self.vpc.public_subnets[0].subnet_id,
                    'ECS_CLUSTER_NAME': self.cluster.cluster_name,
                    'ECS_TASK_DEFINITION': self.task_definition.task_definition_arn
                }
            }
        )
        # Allow Chalice application read/write to Athena bucket
        self.athena_bucket.grant_read_write(self.chalice.get_role('DefaultRole'))
        # Allow Chalice application to interact with Glue table/database
        role = self.chalice.get_role('DefaultRole')
        role.attach_inline_policy(iam.Policy(
            self,
            "ShadowStarChaliceGluePolicy",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=['glue:GetTable'],
                    resources=[
                        f'arn:aws:glue:{self.region}:{self.account}:catalog',
                        f'arn:aws:glue:{self.region}:{self.account}:database/{self.athena_database.database_name}',
                        f'arn:aws:glue:{self.region}:{self.account}:table/{self.athena_database.database_name}/{self.athena_table.table_input.name}'
                    ]
                )
            ]
        ))
        # Allow Chalice to pass the ECS execution role and the update task role
        # so it can invoke auto-update tasks.
        self.task_definition.execution_role.grant_pass_role(role.grant_principal)
        self.task_role.grant_pass_role(role.grant_principal)

    def _create_athena_s3_bucket(self):
        self.athena_bucket = s3.Bucket(
            self,
            f"ShadowStarAthenaBucket",
            encryption=s3.BucketEncryption.UNENCRYPTED,
            public_read_access=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )
        self.athena_bucket.add_cors_rule(
            allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.POST, s3.HttpMethods.HEAD],
            allowed_origins=['*'],
            allowed_headers=['*']
        )

    def _create_athena_database(self):
        self.athena_database = glue.Database(
            self,
            "ShadowStarAthenaDB",
            database_name="shadowstar_athena_db"
        )
        self.athena_table = glue.CfnTable(
            self,
            "ShadowStarAthenaTable",
            database_name=self.athena_database.database_name,
            catalog_id=self.account,
            table_input=glue.CfnTable.TableInputProperty(
                name="shadowstar_athena_table",
                table_type="EXTERNAL_TABLE",
                parameters={
                    'EXTERNAL': "TRUE",
                    'has_encrypted_data': False
                },
                storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                    columns=[
                        glue.CfnTable.ColumnProperty(name="inetnum", type="string"),
                        glue.CfnTable.ColumnProperty(name="netname", type="string"),
                        glue.CfnTable.ColumnProperty(name="description", type="string"),
                        glue.CfnTable.ColumnProperty(name="country", type="string"),
                        glue.CfnTable.ColumnProperty(name="maintained_by", type="string"),
                        glue.CfnTable.ColumnProperty(name="created", type="string"),
                        glue.CfnTable.ColumnProperty(name="last_modified", type="string"),
                        glue.CfnTable.ColumnProperty(name="source", type="string"),
                    ],
                    location=f"s3://{self.athena_bucket.bucket_name}/",
                    input_format="org.apache.hadoop.mapred.TextInputFormat",
                    output_format="org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                    compressed=False,
                    number_of_buckets=-1,
                    serde_info=glue.CfnTable.SerdeInfoProperty(
                        serialization_library="org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
                        parameters={
                            "field.delim": "\t",
                            "serialization.format": "\t"
                        }
                    ),
                    stored_as_sub_directories=False
                ),
            )
        )

    def _create_fargate_cluster(self):
        self.vpc = ec2.Vpc(self, "ShadowStarVPC", max_azs=3)
        self.cluster = ecs.Cluster(self, "ShadowStarCluster", vpc=self.vpc)

    def _create_fargate_task(self):
        self.task_role = iam.Role(
            self,
            "ShadowStarUpdateTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            role_name="ShadowStarUpdateTaskRole",
            description=""
        )
        self.task_role.attach_inline_policy(
            iam.Policy(
                self,
                "ShadowStarUpdateTaskPolicy",
                statements=[
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        actions=['s3:PutObject'],
                        resources=[
                            self.athena_bucket.arn_for_objects('network_info.tsv'),
                            self.athena_bucket.arn_for_objects('metadata/metadata.json')
                        ]
                    ),
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        actions=['secretsmanager:GetSecretValue'],
                        resources=[self.arin_secret_arn]
                    )
                ]
            )
        )
        # 8 GB seems like a lot of memory; but it is needed to hold the large
        # data dumps in memory all at once. You could do this much better with
        # a different language, but good RPSL parsers are hard to find.
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "ShadowStarUpdateTask",
            cpu=1024,
            memory_limit_mib=8192,
            task_role=self.task_role
        )
        self.task_definition.add_container(
            "ShadowStarUpdateTaskContainer",
            image=ecs.ContainerImage.from_asset("../../shadowstar_db_parser"),
            environment={
                "S3_BUCKET": self.athena_bucket.bucket_name,
                "S3_PATH": "network_info.tsv",
                "S3_METADATA_PATH": "metadata/metadata.json",
                "SYSTEM_VERSION": self.system_version,
                "ARIN_SECRET_NAME": self.arin_secret_name
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="ShadowStarUpdateTask",
                log_retention=logs.RetentionDays.ONE_WEEK
            )
        )
