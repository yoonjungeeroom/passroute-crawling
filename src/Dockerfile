# Stage 1: ONNX 임베딩 모델 변환 및 양자화
FROM python:3.11-slim AS embedding-builder

RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir "optimum[onnxruntime]" transformers

# KR-SBERT → ONNX 변환
RUN optimum-cli export onnx \
    --model snunlp/KR-SBERT-V40K-klueNLI-augSTS \
    /tmp/onnx_model/ \
    --task feature-extraction

# 동적 양자화 (~440MB → ~110MB)
RUN python -c "\
from onnxruntime.quantization import quantize_dynamic, QuantType; \
quantize_dynamic('/tmp/onnx_model/model.onnx', '/tmp/kr-sbert-uint8.onnx', weight_type=QuantType.QUInt8)"

# 토크나이저만 별도 저장
RUN python -c "\
from transformers import AutoTokenizer; \
t = AutoTokenizer.from_pretrained('snunlp/KR-SBERT-V40K-klueNLI-augSTS'); \
t.save_pretrained('/tmp/tokenizer/')"


# Stage 2: PaddleOCR 한국어 모델 → ONNX 변환
FROM python:3.11-slim AS ocr-builder

RUN apt-get update && apt-get install -y --no-install-recommends wget libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir paddlepaddle==2.6.2 "paddle2onnx>=1.2,<2.0" packaging

# 한국어 PP-OCRv3 rec 모델 다운로드 및 변환
RUN wget -q https://paddleocr.bj.bcebos.com/PP-OCRv3/multilingual/korean_PP-OCRv3_rec_infer.tar \
    -O /tmp/korean_rec.tar \
    && mkdir -p /tmp/paddle_model \
    && tar -xf /tmp/korean_rec.tar -C /tmp/paddle_model --strip-components=1

RUN mkdir -p /tmp/ocr_models \
    && paddle2onnx \
       --model_dir /tmp/paddle_model \
       --model_filename inference.pdmodel \
       --params_filename inference.pdiparams \
       --save_file /tmp/ocr_models/korean_rec.onnx \
       --opset_version 14

# 한국어 문자 사전 다운로드
RUN wget -q https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/release/2.7/ppocr/utils/dict/korean_dict.txt \
    -O /tmp/ocr_models/korean_dict.txt


# Stage 3: Lambda 런타임
FROM public.ecr.aws/lambda/python:3.11

# 임베딩 모델 복사
COPY --from=embedding-builder /tmp/kr-sbert-uint8.onnx /app/models/kr-sbert-uint8.onnx
COPY --from=embedding-builder /tmp/tokenizer/ /app/models/tokenizer/

# OCR 모델 복사
COPY --from=ocr-builder /tmp/ocr_models/korean_rec.onnx /app/ocr_models/korean_rec.onnx
COPY --from=ocr-builder /tmp/ocr_models/korean_dict.txt /app/ocr_models/korean_dict.txt

# OpenCV 런타임 의존성 (rapidocr-onnxruntime → cv2 → libGL)
RUN yum install -y mesa-libGL && yum clean all

# 의존성 설치
COPY src/requirements-full.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# 소스 코드 복사
COPY src/ ${LAMBDA_TASK_ROOT}/

CMD ["app.job_detail_crawler"]
