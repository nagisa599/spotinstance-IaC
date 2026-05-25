variable "project_name" {
  description = "Tag/Name prefix (must be unique per region)"
  type        = string
}

variable "region" {
  description = "AWS region for this module instance"
  type        = string
}

variable "instance_types" {
  description = "Instance types to test each hour"
  type        = list(string)
}

variable "ddb_table_name" {
  description = "DynamoDB table name for this region's results"
  type        = string
}

variable "lambda_zip_path" {
  description = "Path to the Lambda deployment zip (built in root)"
  type        = string
}

variable "lambda_zip_hash" {
  description = "Base64-encoded SHA256 of the zip (for change detection)"
  type        = string
}

variable "excluded_azs" {
  description = "AZs to exclude from subnet creation (e.g. AZs that don't support certain instance types)"
  type        = list(string)
  default     = []
}
