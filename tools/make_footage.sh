#!/usr/bin/env bash
# Regenerates the benchmark footage. Output is committed to the repo, so this only
# needs to run when the footage itself changes (that is a new suite version).
# Requires ffmpeg 6 or later with libx264 and prores_ks.
set -euo pipefail
OUT="$(cd "$(dirname "$0")/.." && pwd)/assets/footage"
mkdir -p "$OUT"
DUR=6
SIZE=3840x2160

# A: 4K H.264 at about 45 Mbit/s. Moving gradients plus temporal grain keep the
# bitrate and decode cost close to real camera or stock footage.
ffmpeg -hide_banner -y -f lavfi \
  -i "gradients=s=${SIZE}:r=25:speed=0.015:c0=0x1e3a8a:c1=0xf97316:c2=0x10b981:c3=0xfacc15:nb_colors=4:seed=7:d=${DUR},format=yuv420p,noise=alls=16:allf=t+u:all_seed=11" \
  -c:v libx264 -preset medium -profile:v high -level 5.1 -b:v 45M -maxrate 50M -bufsize 100M \
  -g 25 -pix_fmt yuv420p -movflags +faststart -an "$OUT/clip_a_4k_h264.mp4"

# B: 4K ProRes 422 Proxy, the intermediate codec most studios exchange.
# No grain here: ProRes grows with detail and GitHub caps files at 100 MB.
ffmpeg -hide_banner -y -f lavfi \
  -i "testsrc2=s=${SIZE}:r=25:d=${DUR},hue=h=t*40" \
  -c:v prores_ks -profile:v 0 -pix_fmt yuv422p10le -an "$OUT/clip_b_4k_prores_proxy.mov"

# Stills used as textures and overlays.
ffmpeg -hide_banner -y -f lavfi -i "mandelbrot=s=${SIZE}:start_scale=2.5:end_scale=0.4,trim=start_frame=40:end_frame=41" \
  -frames:v 1 -q:v 3 "$OUT/still_mandelbrot_4k.jpg"
ffmpeg -hide_banner -y -f lavfi -i "gradients=s=${SIZE}:nb_colors=5:seed=3,noise=alls=30:all_seed=5" \
  -frames:v 1 -q:v 3 "$OUT/still_texture_4k.jpg"

( cd "$OUT" && sha256sum clip_a_4k_h264.mp4 clip_b_4k_prores_proxy.mov still_mandelbrot_4k.jpg still_texture_4k.jpg > SHA256SUMS )
ls -lh "$OUT"
