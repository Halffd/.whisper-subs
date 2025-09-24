import subprocess
from pathlib import Path

class WhisperModelChooser:
    """Smart Whisper model selection based on available GPU memory"""
    
    def __init__(self, english=False):
        self.english = english
        # Real disk sizes from your du output (in MB)
        self.disk_sizes = {
            "tiny": 75,
            "tiny.en": 75,
            "base": 142,
            "base.en": 141,
            "small": 464,
            "small.en": 464,
            "medium": 1500,  # 1.5G
            "medium.en": 1500,
            "large-v2": 2900,  # 2.9G
            "large-v3": 2900   # 2.9G
        }
        
        # Estimated VRAM usage (disk size + overhead for GPU operations)
        # Based on your binary search results and real-world usage
        self.vram_usage = {
            ("tiny", "int8"): 60,
            ("tiny", "float16"): 90,
            ("tiny", "float32"): 150,
            
            ("base", "int8"): 120,
            ("base", "float16"): 180,
            ("base", "float32"): 300,
            
            ("small", "int8"): 380,
            ("small", "float16"): 580,
            ("small", "float32"): 1000,
            
            ("medium", "int8"): 950,
            ("medium", "float16"): 1400,
            ("medium", "float32"): 2200,
            
            ("large-v2", "int8"): 1800,
            ("large-v2", "float16"): 2700,
            ("large-v2", "float32"): 4200,
            
            ("large-v3", "int8"): 1800,
            ("large-v3", "float16"): 2700,
            ("large-v3", "float32"): 4200,
        }
        
        # Quality ranking (higher = better)
        self.quality_scores = {
            "tiny": 1,
            "tiny.en": 1,
            "base": 2,
            "base.en": 2,
            "small": 3,
            "small.en": 3,
            "medium": 4,
            "medium.en": 4,
            "large-v2": 5,
            "large-v3": 6  # Latest is best
        }

    def get_gpu_memory(self):
        """Get free/total GPU memory in MB"""
        try:
            free_cmd = "nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits"
            total_cmd = "nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits"
            
            free_mem = int(subprocess.check_output(free_cmd.split()).decode().strip())
            total_mem = int(subprocess.check_output(total_cmd.split()).decode().strip())
            
            return free_mem, total_mem
        except Exception as e:
            print(f"⚠️  Could not get GPU memory info: {e}")
            return 0, 0

    def get_model_info(self, model_name, compute_type="float16"):
        """Get detailed info about a model"""
        key = (model_name, compute_type)
        
        return {
            "model": model_name,
            "compute_type": compute_type,
            "disk_size_mb": self.disk_sizes.get(model_name, 0),
            "vram_usage_mb": self.vram_usage.get(key, 0),
            "quality_score": self.quality_scores.get(model_name, 0),
            "is_english_only": model_name.endswith(".en")
        }

    def can_fit_model(self, model_name, compute_type="float16", safety_margin=100):
        """Check if a model can fit in available VRAM"""
        free_mem, total_mem = self.get_gpu_memory()
        print(f"Free VRAM: {free_mem}MB / {total_mem}MB")
        key = (model_name, compute_type)
        
        if key not in self.vram_usage:
            return False, f"Unknown model/compute combination: {key}"
        
        required = self.vram_usage[key] + safety_margin
        
        if free_mem < required:
            return False, f"Need {required}MB, only {free_mem}MB free"
        
        return True, f"Should fit! Need {required}MB, have {free_mem}MB free"
    def get_compatible_models(self, safety_margin=100, english_only=False):
        """Get all models that can fit in current VRAM"""
        free_mem, total_mem = self.get_gpu_memory()
        compatible = []
        
        for (model, compute_type), vram_needed in self.vram_usage.items():
            # Filter models based on english_only flag
            if english_only:
                # Only include .en models OR the base models (tiny, base, small, medium, large)
                if not (model.endswith(".en") or model in ["tiny", "base", "small", "medium", "large"]):
                    continue
            else:
                # Include non en models when english_only=False
                if model.endswith(".en"):
                    continue
                
            if vram_needed + safety_margin <= free_mem:
                info = self.get_model_info(model, compute_type)
                compatible.append(info)
        
        # Sort by quality score (descending), then by VRAM usage (ascending)
        compatible.sort(key=lambda x: (-x["quality_score"], x["vram_usage_mb"]))
        
        return compatible
    def choose_best_model(self, prefer_quality=True, safety_margin=100, english_only=False):
        """Automatically choose the best model for current GPU"""
        free_mem, total_mem = self.get_gpu_memory()
        
        if free_mem == 0:
            print("❌ No GPU detected or nvidia-smi failed")
            return None
        
        print(f"🔍 GPU Memory: {free_mem}MB free / {total_mem}MB total")
        
        compatible = self.get_compatible_models(safety_margin, english_only)
        
        if not compatible:
            print("❌ No models can fit in available VRAM")
            return None
        
        best_model = compatible[0]  # Already sorted by quality
        
        print(f"✅ Best fit: {best_model['model']} ({best_model['compute_type']})")
        print(f"   Quality: {best_model['quality_score']}/6")
        print(f"   VRAM usage: {best_model['vram_usage_mb']}MB")
        print(f"   Disk size: {best_model['disk_size_mb']}MB")
        
        return best_model

    def show_all_options(self, safety_margin=100):
        """Show all available models and their compatibility"""
        free_mem, total_mem = self.get_gpu_memory()
        
        print(f"🎯 Model Compatibility Report")
        print(f"GPU Memory: {free_mem}MB free / {total_mem}MB total")
        print("-" * 80)
        print(f"{'Model':<12} {'Compute':<10} {'VRAM':<8} {'Disk':<8} {'Quality':<8} {'Status'}")
        print("-" * 80)
        
        # Sort by quality score descending
        all_models = []
        for (model, compute_type) in self.vram_usage.keys():
            info = self.get_model_info(model, compute_type)
            can_fit, _ = self.can_fit_model(model, compute_type, safety_margin)
            info["can_fit"] = can_fit
            all_models.append(info)
        
        all_models.sort(key=lambda x: (-x["quality_score"], x["vram_usage_mb"]))
        
        for info in all_models:
            status = "✅ OK" if info["can_fit"] else "❌ Too big"
            print(f"{info['model']:<12} {info['compute_type']:<10} "
                  f"{info['vram_usage_mb']:<8} {info['disk_size_mb']:<8} "
                  f"{info['quality_score']}/6{'':>4} {status}")

# Usage
if __name__ == "__main__":
    chooser = WhisperModelChooser()
    
    # Show all options for your GPU
    chooser.show_all_options()
    
    print("\n" + "="*60 + "\n")
    
    # Auto-choose best model
    best = chooser.choose_best_model()
    
    if best:
        print(f"\n🚀 Loading {best['model']} with {best['compute_type']}...")
        """
        # Your actual model loading code
        import faster_whisper
        whisper_model = faster_whisper.WhisperModel(
            best['model'],
            device="cuda",
            compute_type=best['compute_type'],
            device_index=0,
            cpu_threads=4
        )
        
        print("✅ Model loaded successfully!")
        """