#include <cstdio>
#include <string>
#include <utility>
#include <vector>

#include "options.h"

namespace {

int failures = 0;

void check(bool condition, const std::string& message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL [benchmark_options] %s\n", message.c_str());
    ++failures;
  }
}

void accepts_valid_options() {
  bench_options::Options options;
  std::string error;
  auto status = bench_options::parse_options({}, &options, &error);
  check(status == bench_options::ParseStatus::kOk, "defaults rejected");
  check(options.iterations == bench_options::kDefaultIterations &&
            options.reps == bench_options::kDefaultReps &&
            options.warmup == bench_options::kDefaultWarmup,
        "defaults changed");

  options = {};
  error.clear();
  std::vector<std::string> valid_args;
  valid_args.emplace_back("--iterations");
  valid_args.emplace_back("12");
  valid_args.emplace_back("--reps");
  valid_args.emplace_back("3");
  valid_args.emplace_back("--warmup");
  valid_args.emplace_back("4");
  valid_args.emplace_back("--json");
  status = bench_options::parse_options(valid_args, &options, &error);
  check(status == bench_options::ParseStatus::kOk, "valid options rejected");
  check(options.iterations == 12 && options.reps == 3 && options.warmup == 4,
        "valid values not retained");
  check(options.json, "--json not retained");

  options = {};
  error.clear();
  std::vector<std::string> maximum_args;
  maximum_args.emplace_back("--iterations");
  maximum_args.emplace_back("100000");
  maximum_args.emplace_back("--reps");
  maximum_args.emplace_back("1");
  maximum_args.emplace_back("--warmup");
  maximum_args.emplace_back("100000");
  status = bench_options::parse_options(maximum_args, &options, &error);
  check(status == bench_options::ParseStatus::kOk, "documented maximum values rejected");
}

void rejects_invalid_values() {
  const std::vector<std::pair<std::string, std::vector<std::string>>> cases = {
      {"--iterations", {"", "12junk", "-1", "+1", "0", "2147483648", "100001"}},
      {"--reps", {"", "3tail", "-1", "+1", "0", "2147483648", "1001"}},
      {"--warmup", {"", "3tail", "-1", "+1", "0", "2147483648", "100001"}},
  };

  for (const auto& test_case : cases) {
    for (const std::string& value : test_case.second) {
      bench_options::Options options;
      std::string error;
      const auto status =
          bench_options::parse_options({test_case.first, value}, &options, &error);
      check(status == bench_options::ParseStatus::kError,
            "accepted invalid " + test_case.first + " value: " + value);
      check(error.find(test_case.first) != std::string::npos,
            "error omitted " + test_case.first + " for value: " + value);
    }

    bench_options::Options options;
    std::string error;
    const auto missing =
        bench_options::parse_options({test_case.first}, &options, &error);
    check(missing == bench_options::ParseStatus::kError,
          "accepted missing value for " + test_case.first);
    check(error.find(test_case.first) != std::string::npos,
          "missing-value error omitted " + test_case.first);
  }

  bench_options::Options options;
  std::string error;
  const auto unknown = bench_options::parse_options({"--unknown"}, &options, &error);
  check(unknown == bench_options::ParseStatus::kError, "unknown option accepted");
  check(error.find("--unknown") != std::string::npos,
        "unknown-option error omitted option");
}

void rejects_excessive_combined_work() {
  bench_options::Options options;
  std::string error;
  const auto status = bench_options::parse_options(
      {"--iterations", "100000", "--reps", "2"}, &options, &error);
  check(status == bench_options::ParseStatus::kError,
        "combined timed launch count above limit accepted");
  check(error.find("--iterations") != std::string::npos &&
            error.find("--reps") != std::string::npos,
        "combined-limit error should identify both options");
}

void recognizes_help() {
  bench_options::Options options;
  std::string error;
  const auto status = bench_options::parse_options({"--help"}, &options, &error);
  check(status == bench_options::ParseStatus::kHelp, "--help not recognized");
}

}  // namespace

int main() {
  accepts_valid_options();
  rejects_invalid_values();
  rejects_excessive_combined_work();
  recognizes_help();
  if (failures != 0) {
    std::fprintf(stderr, "benchmark_options: %d failure(s)\n", failures);
    return 1;
  }
  std::printf("OK [benchmark_options] all parser checks passed\n");
  return 0;
}
