from services.phase1_pipeline import Phase1Pipeline

pipeline = Phase1Pipeline(folder_path="sample_data")  # your folder path
chunks = pipeline.run()

print("\nSample chunk:\n", chunks[0] if chunks else "No data")