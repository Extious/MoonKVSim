# Additional observation-transparency validation

After the ten prespecified experiments completed, independent review established that the original Restart F1 flow log was empty. The parent task explicitly authorized one additional nonempty-flow validation, fixed to the existing tight-1.25-GiB DAG DRAM F1 job.

Run the uninstrumented base runtime once from the already-frozen source snapshot with exactly that job config, workload, profile, predictor, failure, and detailed-log mode. Compare its complete summary bytes and decompressed event/flow bytes against the existing observed formal run; do not rerun or replace the formal run. Save hashes, nonempty byte/row counts, and the validation script hash. This is a second validation execution and adds zero experimental samples. It does not change the original ten-run seal, protocol, parameters, or outcomes.
