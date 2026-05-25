output "ddb_table" {
  value = aws_dynamodb_table.results.name
}

output "lambda_start_name" {
  value = aws_lambda_function.start_instances.function_name
}

output "lambda_state_name" {
  value = aws_lambda_function.on_state_change.function_name
}

output "lambda_interrupt_name" {
  value = aws_lambda_function.on_interruption.function_name
}
