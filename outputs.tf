output "ddb_tables" {
  description = "DynamoDB table names per region"
  value = {
    us_east_1      = module.virginia.ddb_table
    ap_northeast_1 = module.tokyo.ddb_table
    eu_west_1      = module.ireland.ddb_table
    ap_southeast_1 = module.singapore.ddb_table
  }
}
