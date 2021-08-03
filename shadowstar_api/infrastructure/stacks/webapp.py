from aws_cdk import (
    aws_s3 as s3,
    aws_iam as iam,
    core as cdk
)


class WebApp(cdk.Stack):

  def __init__(self, scope, id, ingress_cidr_block, **kwargs):
      super().__init__(scope, id, **kwargs)
      self.ingress_cidr_block = ingress_cidr_block
      self._create_webapp_s3_bucket()

  def _create_webapp_s3_bucket(self):
    self.webapp_bucket = s3.Bucket(
        self,
        f"ShadowStarWebappBucket",
        encryption=s3.BucketEncryption.UNENCRYPTED,
        public_read_access=False,
        block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
    )
    policy = iam.PolicyStatement(
        effect=iam.Effect.ALLOW,
        actions=['s3:GetObject'],
        resources=[self.webapp_bucket.arn_for_objects('*')],
        principals=[iam.AnyPrincipal()]
    )
    policy.add_condition('IpAddress', {
        "aws:SourceIp": [self.ingress_cidr_block]
    })
    self.webapp_bucket.add_to_resource_policy(
        policy            
    )
    self.webapp_bucket.add_cors_rule(
        allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.POST, s3.HttpMethods.HEAD],
        allowed_origins=['*'],
        allowed_headers=['*']
    )
    cdk.CfnOutput(
        self,
        'OutputWebappBucket',
        value=self.webapp_bucket.bucket_name,
        description='The S3 bucket which hosts the web application',
        export_name='ShadowStarWebappBucket'
    )
