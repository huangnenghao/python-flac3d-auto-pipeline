import os
import numpy as np
from PIL import Image

def process_images():
    # Configuration
    project_dir = r"d:\2026.03 FLAC3D Code-Native"
    input_dir = os.path.join(project_dir, "data", "longrongrelia", "plots")
    output_heatmap = os.path.join(project_dir, "data", "longrongrelia", "failure_probability_heatmap.png")
    output_composite = os.path.join(project_dir, "data", "longrongrelia", "failure_zone_composite.png")
    
    if not os.path.exists(input_dir):
        print(f"Error: Input directory not found: {input_dir}")
        return

    # 1. Collect image files
    image_files = sorted([f for f in os.listdir(input_dir) if f.startswith("strain_increment") and f.endswith(".png")])
    
    if not image_files:
        print("No strain_increment images found.")
        return

    print(f"Found {len(image_files)} images. Processing...")

    # Initialize arrays
    first_img = Image.open(os.path.join(input_dir, image_files[0])).convert("RGB")
    width, height = first_img.size
    
    # Array for "Minimum Blending" (Darkest pixel wins - shows union of failure zones)
    # Initialize with white (255)
    min_blend = np.full((height, width, 3), 255, dtype=np.uint8)
    
    # Array for "Probability Heatmap" (Count how many times a pixel is 'failure color')
    # We assume 'failure' is anything significantly non-white.
    failure_count = np.zeros((height, width), dtype=np.float32)
    
    count = 0
    for img_file in image_files:
        try:
            img_path = os.path.join(input_dir, img_file)
            img = Image.open(img_path).convert("RGB")
            
            # Ensure size matches
            if img.size != (width, height):
                img = img.resize((width, height))
            
            arr = np.array(img)
            
            # Update Minimum Blend
            # We want the darkest pixel at each position across all images
            min_blend = np.minimum(min_blend, arr)
            
            # Update Failure Count
            # Define 'failure' as pixels that are NOT white (or close to white)
            # Threshold: if R, G, and B are all > 240, it's background/white
            is_white = (arr[:,:,0] > 240) & (arr[:,:,1] > 240) & (arr[:,:,2] > 240)
            is_failure = ~is_white
            
            failure_count[is_failure] += 1.0
            count += 1
            
            if count % 10 == 0:
                print(f"  Processed {count}/{len(image_files)}...")
                
        except Exception as e:
            print(f"  Error reading {img_file}: {e}")

    # Save Minimum Blend Composite
    Image.fromarray(min_blend).save(output_composite)
    print(f"Saved Composite Image (Union of Failures) to: {output_composite}")
    
    # Save Probability Heatmap
    if count > 0:
        # Normalize to 0-255
        # Max value is 'count' (100% failure probability)
        # We want: 0% -> Transparent/White, 100% -> Red/Dark
        
        # Simple normalization for visualization
        # Map 0..count to 0..255
        heatmap_norm = (failure_count / count * 255).astype(np.uint8)
        
        # Create a colored heatmap (Red intensity = Probability)
        # Background (0 count) should be white
        # High count should be red
        
        # Initialize white image
        heatmap_img = np.full((height, width, 3), 255, dtype=np.uint8)
        
        # Apply color ramp
        # Let's make it Red: (255, 255-val, 255-val) -> 0 gives white, 255 gives pure red
        heatmap_img[:,:,1] = 255 - heatmap_norm
        heatmap_img[:,:,2] = 255 - heatmap_norm
        # Red channel stays 255 (or can be darkened for very high probability)
        
        Image.fromarray(heatmap_img).save(output_heatmap)
        print(f"Saved Probability Heatmap to: {output_heatmap}")

if __name__ == "__main__":
    process_images()
