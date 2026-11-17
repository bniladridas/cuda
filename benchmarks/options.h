#pragma once

// Pure host-side parsing for benchmark command-line options. Kept independent
// of CUDA so validation can be tested in CPU-only builds.

#include <charconv>
#include <cstddef>
#include <cstdint>
#include <string>
#include <system_error>
#include <vector>

namespace bench_options {

constexpr int kDefaultIterations = 200;
constexpr int kDefaultReps = 7;
constexpr int kDefaultWarmup = 20;
constexpr int kMaxIterations = 100000;
constexpr int kMaxReps = 1000;
constexpr int kMaxWarmup = 100000;
constexpr std::int64_t kMaxTimedLaunches = 100000;

struct Options {
  int iterations = kDefaultIterations;
  int reps = kDefaultReps;
  int warmup = kDefaultWarmup;
  bool json = false;
};

enum class ParseStatus { kOk, kHelp, kError };

inline bool parse_positive_integer(const std::string& value, int maximum, int* out) {
  if (value.empty()) return false;
  for (char ch : value) {
    if (ch < '0' || ch > '9') return false;
  }

  int parsed = 0;
  const char* const begin = value.data();
  const char* const end = begin + value.size();
  const auto result = std::from_chars(begin, end, parsed);
  if (result.ec != std::errc{} || result.ptr != end || parsed <= 0 || parsed > maximum) {
    return false;
  }
  *out = parsed;
  return true;
}

inline ParseStatus parse_options(const std::vector<std::string>& args, Options* opts,
                                std::string* error) {
  for (std::size_t i = 0; i < args.size(); ++i) {
    const std::string& arg = args[i];
    if (arg == "--help" || arg == "-h") return ParseStatus::kHelp;
    if (arg == "--json") {
      opts->json = true;
      continue;
    }

    int* destination = nullptr;
    int maximum = 0;
    if (arg == "--iterations") {
      destination = &opts->iterations;
      maximum = kMaxIterations;
    } else if (arg == "--reps") {
      destination = &opts->reps;
      maximum = kMaxReps;
    } else if (arg == "--warmup") {
      destination = &opts->warmup;
      maximum = kMaxWarmup;
    } else {
      *error = "unknown argument: " + arg;
      return ParseStatus::kError;
    }

    if (i + 1 >= args.size()) {
      *error = "missing value for " + arg;
      return ParseStatus::kError;
    }
    const std::string& value = args[++i];
    if (!parse_positive_integer(value, maximum, destination)) {
      *error = "invalid value for " + arg + ": '" + value +
               "' (expected a positive decimal integer no greater than " +
               std::to_string(maximum) + ")";
      return ParseStatus::kError;
    }
  }

  if (static_cast<std::int64_t>(opts->iterations) * opts->reps > kMaxTimedLaunches) {
    *error = "--iterations * --reps exceeds the maximum of " +
             std::to_string(kMaxTimedLaunches) + " timed launches";
    return ParseStatus::kError;
  }
  return ParseStatus::kOk;
}

}  // namespace bench_options
