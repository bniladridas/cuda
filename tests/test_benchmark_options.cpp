#include <cstdio>
#include <string>
#include <vector>

#include "options.h"

namespace {

int failures = 0;

void check(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL [benchmark_options] %s\n", message);
    ++failures;
  }
}

void accepts_valid_options() {
  bench_options::Options options;
  std::string error;
  const auto status = bench_options::parse_options(
      {"--iterations", "12", "--reps", "3", "--warmup", "0"}, &options, &error);
  check(status == bench_options::ParseStatus::kError,
        "zero warmup must be rejected");
  check(error.find("--warmup") != std::string::npos,
        "zero warmup error should name its option");

  options = {};
  error.clear();
  const auto valid = bench_options::parse_options(
      {"--iterations", "12", "--reps", "3", "--warmup", "4", "--json"},
      &options, &error);
  check(valid == bench_options::ParseStatus::kOk, "valid options rejected");
  check(options.iterations == 12 && options.reps == 3 && options.warmup == 4,
        "valid values not retained");
  check(options.json, "--json not retained");

  options = {};
  error.clear();
  const auto defaults = bench_options::parse_options({}, &options, &error);
  check(defaults == bench_options::ParseStatus::kOk, "defaults rejected");
  check(options.iterations == bench_options::kDefaultIterations &&
            options.reps == bench_options::kDefaultReps &&
            options.warmup == bench_options::kDefaultWarmup,
        "defaults changed");
}

void rejects_invalid_values() {
  const std::vector<std::string> invalid_values = {
      "", "12junk", "-1", "+1", "0", "2147483648", "100001"};
  for (const std::string& value : invalid_values) {
    bench_options::Options options;
    std::string error;
    const auto status = bench_options::parse_options(
        {"--iterations", value}, &options, &error);
    check(status == bench_options::ParseStatus::kError,
          ("accepted invalid --iterations value: " + value).c_str());
    check(error.find("--iterations") != std::string::npos,
          ("error omitted --iterations for value: " + value).c_str());
  }

  bench_options::Options options;
  std::string error;
  auto status = bench_options::parse_options({"--reps"}, &options, &error);
  check(status == bench_options::ParseStatus::kError, "missing --reps value accepted");
  check(error.find("--reps") != std::string::npos, "missing-value error omitted --reps");

  error.clear();
  status = bench_options::parse_options({"--unknown"}, &options, &error);
  check(status == bench_options::ParseStatus::kError, "unknown option accepted");
  check(error.find("--unknown") != std::string::npos, "unknown-option error omitted option");
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
