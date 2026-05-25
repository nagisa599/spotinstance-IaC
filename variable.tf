variable "instance_types" {
  description = "Instance types to test each hour (applied to all regions)"
  type        = list(string)
  default     = ["t3.micro", "c6a.large", "g4dn.xlarge"]
}
