#!/usr/bin/env bash
# 임베딩 호스트 의존성: 코어 → torch → sentence-transformers 순서
#
# 경량화 요약 (sentence-transformers 유지):
#   • PyPI 기본 `pip install sentence-transformers` 는 Linux 에서 CUDA·nvidia-* 번들 torch 를 끌어와 수 GB 쓴다.
#   • `cpu` 모드는 PyTorch **CPU 전용 인덱스**만 써 그 번들을 건너뛴다(가장 큰 절감).
#   • sentence-transformers 는 PyPI 에서 torch 를 **필수**로 선언한다 → 공식 경로만으로 torch 완전 삭제는 사실상 불가.
#   • ONNX/OpenVINO 백엔드 등은 선택(추가 설치 필요); 디스크·의존성 복잡도 대비 이득은 환경마다 다름.
#
#   bash install_deps.sh cpu    # EC2 권장 (CPU torch)
#   bash install_deps.sh gpu    # PyPI 기본 torch (CUDA 번들, 대용량)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-cpu}"
EXTRA_PIP=(--no-cache-dir)
if [[ -n "${PIP_INDEX_URL:-}" ]]; then EXTRA_PIP+=(--index-url "$PIP_INDEX_URL"); fi

# 구버전 monolithic requirements.txt (sentence-transformers 직접 나열) 은 pip 가 CUDA torch 를 끌어와 디스크를 망가뜨린다.
if [[ -f "$DIR/requirements.txt" ]] && grep -qE '^[[:space:]]*sentence-transformers' "$DIR/requirements.txt"; then
  echo "오류: embedding/requirements.txt 가 예전 형식입니다(줄이 sentence-transformers 로 시작함)." >&2
  echo "  레포 최신을 받으세요: git pull  (또는 로컬에서 deploy/rsync)" >&2
  echo "  그 다음:  cd embedding && bash install_deps.sh cpu" >&2
  echo "  ※ pip install -r requirements.txt 만으로 옛 파일을 쓰면 대용량 CUDA 번들이 설치됩니다." >&2
  exit 1
fi

pip install "${EXTRA_PIP[@]}" -r "$DIR/requirements-core.txt"
case "$MODE" in
  cpu)
    pip install "${EXTRA_PIP[@]}" torch --index-url https://download.pytorch.org/whl/cpu
    ;;
  gpu|cuda)
    echo "gpu: PyPI 기본 torch (CUDA·nvidia wheels, 디스크 많이 사용)" >&2
    pip install "${EXTRA_PIP[@]}" 'torch>=2.2,<3'
    ;;
  *)
    echo "usage: $0 [cpu|gpu]  (default: cpu)" >&2
    exit 1
    ;;
esac
pip install "${EXTRA_PIP[@]}" -r "$DIR/requirements-embed.txt"
echo "embedding deps OK (mode=$MODE)"
