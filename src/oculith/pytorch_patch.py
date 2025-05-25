# 1. 只开启 MPS 回退，不禁全局 CUDA，也不改全局默认 device
import os
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'

# 2. 针对公式理解模型打补丁：把 predict 强制搬到 CPU
try:
    import torch
    # 引入模型和构造停止条件所需的类
    from transformers import StoppingCriteriaList
    from docling_ibm_models.code_formula_model.code_formula_predictor import (
        CodeFormulaPredictor, StopOnString
    )

    _orig_predict = CodeFormulaPredictor.predict

    def _mps_optimized_predict(self, images, labels, temperature=None):
        # --- 复制原 predict 前置逻辑 ---
        from PIL import Image
        import numpy as np

        images_tmp = []
        for image in images:
            if isinstance(image, Image.Image):
                image = image.convert("RGB")
            elif isinstance(image, np.ndarray):
                from PIL import Image as _Img
                image = _Img.fromarray(image).convert("RGB")
            images_tmp.append(image)
        images_tensor = torch.stack(
            [self._image_processor(img) for img in images_tmp]
        ).to(self._device)

        prompts = [self._get_prompt(label) for label in labels]
        tokenized = self._tokenizer(prompts, padding=True, return_tensors="pt")
        tokenized = {k: v.to(self._device) for k, v in tokenized.items()}
        prompt_ids = tokenized["input_ids"]
        attention_mask = tokenized["attention_mask"]

        # --- 重新构造 stopping_criteria ---
        stopping_criteria = StoppingCriteriaList([
            StopOnString(self._tokenizer, r" \quad \quad \quad \quad"),
            StopOnString(self._tokenizer, r" \\ \\ \\ \\"),
            StopOnString(self._tokenizer, r" \, \, \, \,"),
            StopOnString(self._tokenizer, r" c c c c c c c c c c c c c c c c"),
            StopOnString(self._tokenizer, r" l l l l l l l l l l l l l l l l"),
        ])

        # MPS 分支：直接用 float32，带 attention_mask，不用 autocast
        if self._device != "cpu":
            output_ids_list = self._model.generate(
                input_ids=prompt_ids,
                attention_mask=attention_mask,
                images=images_tensor,
                do_sample=(temperature is not None and temperature > 0),
                temperature=temperature if temperature and temperature > 0 else None,
                max_new_tokens=4096 - prompt_ids.shape[1],
                use_cache=True,
                no_repeat_ngram_size=200,
                stopping_criteria=stopping_criteria,
            )
        else:
            # CPU 分支：调用原始 predict（含 autocast、bfloat16）
            output_ids_list = _orig_predict(self, images, labels, temperature)

        # 批量解码并去尾
        outputs = self._tokenizer.batch_decode(
            output_ids_list[:, prompt_ids.shape[1]:],
            skip_special_tokens=True
        )
        return [self._strip(o) for o in outputs]

    # 应用补丁
    CodeFormulaPredictor.predict = _mps_optimized_predict

except ImportError:
    # 异常时忽略，保持 docling_ibm_models 的默认行为
    pass

# 3. 然后再 import torch，不要全局改 default device
import torch
