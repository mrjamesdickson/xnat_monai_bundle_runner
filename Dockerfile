FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

RUN pip install --no-cache-dir \
    "monai[nibabel,itk,tqdm]==1.5.0" \
    huggingface_hub \
    pytorch-ignite \
    einops \
    fire \
    scikit-image

COPY run_bundle.sh /opt/runner/run_bundle.sh
RUN chmod +x /opt/runner/run_bundle.sh

# Bundles download here at runtime; mount a volume to cache across runs
RUN mkdir -p /bundles /input /output

ENTRYPOINT ["/opt/runner/run_bundle.sh"]
