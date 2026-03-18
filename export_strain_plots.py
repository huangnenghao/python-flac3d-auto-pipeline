# export_strain_plots.py
# -----------------------------------------------------------------------------
# Script to be run INSIDE FLAC3D (via File -> Open -> Python Script or console)
# -----------------------------------------------------------------------------

import itasca as it
import os
it.command("python-reset-state false")

def main():
    # 1. Configuration
    # Adjust these paths if necessary
    project_dir = r"d:\2026.03 FLAC3D Code-Native"
    data_dir = r"d:\2026.03 FLAC3D Code-Native\data\longrongrelia\output"
    output_plot_dir = os.path.join(project_dir, "data", "longrongrelia", "plots")
    
    # Ensure output directory exists
    if not os.path.exists(output_plot_dir):
        os.makedirs(output_plot_dir)
        print(f"Created plot directory: {output_plot_dir}")

    print(f"Scanning for files in: {data_dir}")

    # 2. Iterate through 1 to 100
    count = 0
    for i in range(1, 101):
        # Construct filename: FOS-Unstable01.sav
        sav_filename = f"FOS-Unstable{i:02d}.sav"
        sav_path = os.path.join(data_dir, sav_filename)
        
        # Check if file exists
        if not os.path.exists(sav_path):
            # Try alternative naming if needed (e.g. FOS-Unstable1.sav instead of 01)
            # But based on ls output, it's 01, 02...
            continue
            
        print(f"Processing [{i}/100]: {sav_filename}...")
        
        try:
            # A. Restore the model
            # We use it.command to execute the FLAC3D command
            it.command(f"model restore '{sav_path}'")
            
            # B. Export the plot
            # Output filename: strain_increment01.png
            png_filename = f"strain_increment{i:02d}.png"
            png_path = os.path.join(output_plot_dir, png_filename)
            
            # Ensure the path uses forward slashes or escaped backslashes for FLAC3D command
            # FLAC3D commands often handle paths better with forward slashes
            safe_png_path = png_path.replace("\\", "/")
            
            # Command: plot 'strain increment' export bitmap filename '...' size 2048 768
            # Note: This requires a plot named 'strain increment' to exist in the GUI
            it.command(f"plot 'strain increment' export bitmap filename '{safe_png_path}' size 2048 768")
            
            count += 1
            
        except Exception as e:
            print(f"  [Error] Failed to process {sav_filename}: {e}")

    print(f"\nBatch export finished. {count} images exported to:\n{output_plot_dir}")

if __name__ == "__main__":
    main()
