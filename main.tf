terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# デフォルトプロバイダー（IAMなどグローバルリソース用）
provider "aws" {
  profile = "nislab"
  region  = "us-east-1"
}

provider "aws" {
  alias   = "virginia"
  profile = "nislab"
  region  = "us-east-1"
}

provider "aws" {
  alias   = "tokyo"
  profile = "nislab"
  region  = "ap-northeast-1"
}

provider "aws" {
  alias   = "ireland"
  profile = "nislab"
  region  = "eu-west-1"
}

provider "aws" {
  alias   = "singapore"
  profile = "nislab"
  region  = "ap-southeast-1"
}

# Lambda zip（全リージョン共通コード）
data "archive_file" "start_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/lambda_build/start.zip"
  excludes    = [".DS_Store"]
}

# === 実験モジュール（リージョン別） ===

module "virginia" {
  source          = "./modules/spot-experiment"
  providers       = { aws = aws.virginia }
  project_name    = "spot-exp-2025-virginia"
  region          = "us-east-1"
  instance_types  = var.instance_types
  ddb_table_name  = "spot-exp-results-virginia"
  lambda_zip_path = data.archive_file.start_zip.output_path
  lambda_zip_hash = data.archive_file.start_zip.output_base64sha256
  excluded_azs    = ["us-east-1a"]
}

module "tokyo" {
  source          = "./modules/spot-experiment"
  providers       = { aws = aws.tokyo }
  project_name    = "spot-exp-2025-tokyo"
  region          = "ap-northeast-1"
  instance_types  = var.instance_types
  ddb_table_name  = "spot-exp-results-tokyo"
  lambda_zip_path = data.archive_file.start_zip.output_path
  lambda_zip_hash = data.archive_file.start_zip.output_base64sha256
  excluded_azs    = ["ap-northeast-1a", "ap-northeast-1d"]
}

module "ireland" {
  source          = "./modules/spot-experiment"
  providers       = { aws = aws.ireland }
  project_name    = "spot-exp-2025-ireland"
  region          = "eu-west-1"
  instance_types  = var.instance_types
  ddb_table_name  = "spot-exp-results-ireland"
  lambda_zip_path = data.archive_file.start_zip.output_path
  lambda_zip_hash = data.archive_file.start_zip.output_base64sha256
}

module "singapore" {
  source          = "./modules/spot-experiment"
  providers       = { aws = aws.singapore }
  project_name    = "spot-exp-2025-singapore"
  region          = "ap-southeast-1"
  instance_types  = var.instance_types
  ddb_table_name  = "spot-exp-results-singapore"
  lambda_zip_path = data.archive_file.start_zip.output_path
  lambda_zip_hash = data.archive_file.start_zip.output_base64sha256
}

# === FIS ロール（IAMはグローバル、1つだけ作成） ===
resource "aws_iam_role" "fis_role" {
  name = "fis-experiment-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "fis.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "fis_operator" {
  name        = "fis-operator"
  description = "Allow creating/starting FIS experiments and pass the FIS execution role"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "fis:CreateExperimentTemplate",
          "fis:UpdateExperimentTemplate",
          "fis:DeleteExperimentTemplate",
          "fis:StartExperiment",
          "fis:StopExperiment",
          "fis:Get*",
          "fis:List*",
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = aws_iam_role.fis_role.arn
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "fis.amazonaws.com"
          }
        }
      },
    ]
  })
}

resource "aws_iam_user_policy_attachment" "attach_fis_operator" {
  user       = "nagisa_nasu"
  policy_arn = aws_iam_policy.fis_operator.arn
}
