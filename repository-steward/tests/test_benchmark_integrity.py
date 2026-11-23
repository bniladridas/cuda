import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.benchmark_integrity import analyze_benchmarks, validate_benchmark_result


class BenchmarkIntegrityTests(unittest.TestCase):
    def valid_result(self):
        return {
            "git_commit": "a" * 40,
            "timestamp_utc": "2026-11-23T00:00:00Z",
            "gpu": "Test GPU",
            "device_uuid": "12345678-1234-1234-1234-123456789abc",
            "pci_bus_id": "0000:01:00.0",
            "compute_capability": "8.0",
            "driver": "550.00",
            "cuda_runtime": "12.6",
            "iterations_per_batch": 10,
            "batches": 5,
            "warmup": 2,
            "results": [
                {"kernel": "vecadd", "n": 1024, "median_ms": 0.2, "min_ms": 0.1, "p90_ms": 0.3, "gb_per_s": 4.0}
            ],
        }

    def test_complete_result_is_valid_but_does_not_authorize_claim(self):
        result = validate_benchmark_result(self.valid_result())
        self.assertEqual(result["state"], "valid")
        self.assertFalse(result["performance_claim_authorized"])

    def test_missing_provenance_is_incomplete(self):
        result = validate_benchmark_result({"results": []})
        self.assertEqual(result["state"], "incomplete")
        self.assertFalse(result["publishable"])

    def test_non_finite_measurements_are_rejected(self):
        data = self.valid_result()
        data["results"][0]["median_ms"] = float("nan")
        self.assertEqual(validate_benchmark_result(data)["state"], "incomplete")

    def test_empty_benchmark_list_is_reported(self):
        result = analyze_benchmarks([])
        self.assertEqual(result["result_count"], 0)
        self.assertFalse(result["performance_claims_published"])


if __name__ == "__main__":
    unittest.main()
