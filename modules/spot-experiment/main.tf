# === VPC ===
resource "aws_vpc" "experiment" {
  cidr_block           = "10.100.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name    = "${var.project_name}-vpc"
    Project = var.project_name
  }
}

resource "aws_internet_gateway" "experiment" {
  vpc_id = aws_vpc.experiment.id

  tags = {
    Name    = "${var.project_name}-igw"
    Project = var.project_name
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  target_azs = [
    for az in slice(data.aws_availability_zones.available.names, 0, 3) :
    az if !contains(var.excluded_azs, az)
  ]
}

resource "aws_subnet" "public" {
  for_each                = toset(local.target_azs)
  vpc_id                  = aws_vpc.experiment.id
  cidr_block              = cidrsubnet("10.100.0.0/16", 8, index(data.aws_availability_zones.available.names, each.key))
  availability_zone       = each.key
  map_public_ip_on_launch = true

  tags = {
    Name    = "${var.project_name}-public-${each.key}"
    Project = var.project_name
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.experiment.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.experiment.id
  }

  tags = {
    Name    = "${var.project_name}-public-rt"
    Project = var.project_name
  }
}

resource "aws_route_table_association" "public_assoc" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

# === AMI（リージョンごとに異なるIDをSSMから取得） ===
data "aws_ssm_parameter" "al2023_ami_x86" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
}

# === DynamoDB ===
resource "aws_dynamodb_table" "results" {
  name         = var.ddb_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"

  attribute {
    name = "run_id"
    type = "S"
  }

  global_secondary_index {
    name            = "by_instance_id"
    hash_key        = "instance_id"
    projection_type = "ALL"
  }

  attribute {
    name = "instance_id"
    type = "S"
  }

  tags = {
    Project = var.project_name
  }
}

# === EC2 Instance Role ===
resource "aws_iam_role" "ec2_role" {
  name               = "${var.project_name}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_policy" "ec2_ddb_update" {
  name   = "${var.project_name}-ec2-ddb-update"
  policy = data.aws_iam_policy_document.ec2_ddb_update.json
}

data "aws_iam_policy_document" "ec2_ddb_update" {
  statement {
    sid    = "UpdateItem"
    effect = "Allow"
    actions = [
      "dynamodb:UpdateItem",
      "dynamodb:PutItem",
      "dynamodb:GetItem",
    ]
    resources = [aws_dynamodb_table.results.arn]
  }
}

resource "aws_iam_role_policy_attachment" "ec2_ddb_attach" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.ec2_ddb_update.arn
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2_role.name
}

# === Lambda Role ===
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "lambda_role" {
  name               = "${var.project_name}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda_policy" {
  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["*"]
  }

  statement {
    sid    = "EC2Control"
    effect = "Allow"
    actions = [
      "ec2:RunInstances",
      "ec2:TerminateInstances",
      "ec2:DescribeInstances",
      "ec2:DescribeSubnets",
      "ec2:DescribeAvailabilityZones",
      "ec2:DescribeSpotPriceHistory",
      "ec2:CreateTags",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "DDBAccess"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:GetItem",
      "dynamodb:Query",
    ]
    resources = [aws_dynamodb_table.results.arn, "${aws_dynamodb_table.results.arn}/index/*"]
  }

  statement {
    sid       = "PassInstanceRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.ec2_role.arn]
  }
}

resource "aws_iam_policy" "lambda_policy" {
  name   = "${var.project_name}-lambda-policy"
  policy = data.aws_iam_policy_document.lambda_policy.json
}

resource "aws_iam_role_policy_attachment" "lambda_policy_attach" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}

# === Security Group（EC2用：Outboundのみ） ===
resource "aws_security_group" "ec2_sg" {
  name        = "${var.project_name}-ec2-sg"
  description = "Outbound-only for experiment instances"
  vpc_id      = aws_vpc.experiment.id

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project_name
  }
}

# === Lambda: start_instances ===
resource "aws_lambda_function" "start_instances" {
  function_name    = "${var.project_name}-start-instances"
  role             = aws_iam_role.lambda_role.arn
  handler          = "start_instances.handler"
  runtime          = "python3.12"
  filename         = var.lambda_zip_path
  source_code_hash = var.lambda_zip_hash
  timeout          = 180

  environment {
    variables = {
      TABLE_NAME            = aws_dynamodb_table.results.name
      REGION                = var.region
      AMI_ID                = data.aws_ssm_parameter.al2023_ami_x86.value
      INSTANCE_PROFILE_NAME = aws_iam_instance_profile.ec2_profile.name
      SECURITY_GROUP_ID     = aws_security_group.ec2_sg.id
      SUBNET_IDS_JSON       = jsonencode([for s in aws_subnet.public : s.id])
      INSTANCE_TYPES_JSON   = jsonencode(var.instance_types)
      PROJECT_TAG           = var.project_name
    }
  }
}

resource "aws_cloudwatch_log_group" "lg_start" {
  name              = "/aws/lambda/${aws_lambda_function.start_instances.function_name}"
  retention_in_days = 14
}

# === Lambda: on_state_change ===
resource "aws_lambda_function" "on_state_change" {
  function_name    = "${var.project_name}-on-state-change"
  role             = aws_iam_role.lambda_role.arn
  handler          = "on_state_change.handler"
  runtime          = "python3.12"
  filename         = var.lambda_zip_path
  source_code_hash = var.lambda_zip_hash
  timeout          = 120

  environment {
    variables = {
      TABLE_NAME  = aws_dynamodb_table.results.name
      REGION      = var.region
      PROJECT_TAG = var.project_name
    }
  }
}

resource "aws_cloudwatch_log_group" "lg_state" {
  name              = "/aws/lambda/${aws_lambda_function.on_state_change.function_name}"
  retention_in_days = 14
}

# === Lambda: on_interruption ===
resource "aws_lambda_function" "on_interruption" {
  function_name    = "${var.project_name}-on-interruption"
  role             = aws_iam_role.lambda_role.arn
  handler          = "on_interruption.handler"
  runtime          = "python3.12"
  filename         = var.lambda_zip_path
  source_code_hash = var.lambda_zip_hash
  timeout          = 60

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.results.name
      REGION     = var.region
    }
  }
}

resource "aws_cloudwatch_log_group" "lg_intr" {
  name              = "/aws/lambda/${aws_lambda_function.on_interruption.function_name}"
  retention_in_days = 14
}

# === EventBridge: 毎時トリガー ===
resource "aws_cloudwatch_event_rule" "hourly" {
  name                = "${var.project_name}-hourly"
  description         = "Run spot experiment every hour"
  schedule_expression = "cron(0 * * * ? *)"
}

resource "aws_cloudwatch_event_target" "hourly_to_start" {
  rule      = aws_cloudwatch_event_rule.hourly.name
  target_id = "startInstances"
  arn       = aws_lambda_function.start_instances.arn
}

resource "aws_lambda_permission" "allow_events_to_start" {
  statement_id  = "AllowEventsToInvokeStart"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.start_instances.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hourly.arn
}

# === EventBridge: EC2状態変化 ===
resource "aws_cloudwatch_event_rule" "ec2_state" {
  name        = "${var.project_name}-ec2-state"
  description = "Catch EC2 state-change notifications"
  event_pattern = jsonencode({
    "source"      = ["aws.ec2"]
    "detail-type" = ["EC2 Instance State-change Notification"]
    "detail" = {
      "state" = ["running", "terminated"]
    }
  })
}

resource "aws_cloudwatch_event_target" "state_to_lambda" {
  rule      = aws_cloudwatch_event_rule.ec2_state.name
  target_id = "onStateChange"
  arn       = aws_lambda_function.on_state_change.arn
}

resource "aws_lambda_permission" "allow_events_to_state" {
  statement_id  = "AllowEventsToInvokeState"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.on_state_change.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ec2_state.arn
}

# === EventBridge: Spot中断警告 ===
resource "aws_cloudwatch_event_rule" "spot_interrupt" {
  name        = "${var.project_name}-spot-interruption"
  description = "Catch EC2 Spot Instance Interruption Warning"
  event_pattern = jsonencode({
    "source"      = ["aws.ec2"]
    "detail-type" = ["EC2 Spot Instance Interruption Warning"]
  })
}

resource "aws_cloudwatch_event_target" "interrupt_to_lambda" {
  rule      = aws_cloudwatch_event_rule.spot_interrupt.name
  target_id = "onInterruption"
  arn       = aws_lambda_function.on_interruption.arn
}

resource "aws_lambda_permission" "allow_events_to_interrupt" {
  statement_id  = "AllowEventsToInvokeInterruption"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.on_interruption.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.spot_interrupt.arn
}
