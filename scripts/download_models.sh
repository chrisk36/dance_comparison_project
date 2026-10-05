#!/usr/bin/env bash
# Download MediaPipe PoseLandmarker models into models/ (gitignored).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p models
for variant in "${@:-full heavy}"; do
  for m in $variant; do
    out="models/pose_landmarker_${m}.task"
    [[ -s "$out" ]] && { echo "have $out"; continue; }
    echo "downloading $out"
    curl -fL --retry 5 --retry-all-errors --connect-timeout 10 -o "$out" \
      "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_${m}/float16/latest/pose_landmarker_${m}.task"
  done
done
