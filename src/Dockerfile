# Stage 1: ONNX 모델 변환 및 양자화
FROM python:3.11-slim AS builder

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


# Stage 2: Lambda 런타임
FROM public.ecr.aws/lambda/python:3.11

# 양자화 모델 + 토크나이저 복사
COPY --from=builder /tmp/kr-sbert-uint8.onnx /app/models/kr-sbert-uint8.onnx
COPY --from=builder /tmp/tokenizer/ /app/models/tokenizer/

# 의존성 설치
COPY src/requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# 소스 코드 복사
COPY src/ ${LAMBDA_TASK_ROOT}/

CMD ["app.job_detail_crawler"]
