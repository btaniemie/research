import fitz  
import re
import os

INPUT_FOLDER = "pdfs"
OUTPUT_DIR = "oral_testimonies"
START_PHRASE = "En la Ciudad de los Reyes"
END_PHRASE = "Eusebio de Arrieta"

def process_pdfs():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    if not os.path.exists(INPUT_FOLDER):
        print(f"Error: Folder '{INPUT_FOLDER}' not found.")
        return

    pdf_files = [f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith('.pdf')]
    
    for pdf_name in pdf_files:
        # create a folder for each PDF (e.g., "vol1")
        pdf_stem = os.path.splitext(pdf_name)[0]
        pdf_output_folder = os.path.join(OUTPUT_DIR, pdf_stem)
        if not os.path.exists(pdf_output_folder):
            os.makedirs(pdf_output_folder)
            
        path = os.path.join(INPUT_FOLDER, pdf_name)
        print(f"\n--- Entering Folder: {pdf_stem} (Processing {pdf_name}) ---")
        
        doc = fitz.open(path)
        content_buffer = []
        is_recording = False
        start_page = 0
        testimony_count = 1

        for page in doc:
            page_num = page.number + 1  
            text = page.get_text("text")

            if not is_recording:
                if START_PHRASE in text:
                    is_recording = True
                    start_page = page_num
                    parts = text.split(START_PHRASE, 1)
                    content_buffer.append(START_PHRASE + parts[1])
            else:
                if END_PHRASE in text:
                    parts = text.split(END_PHRASE, 1)
                    content_buffer.append(parts[0] + END_PHRASE)
                    
                    full_testimony = "".join(content_buffer).strip()
                    
                    # naming: vol_page_index.txt
                    filename = f"{pdf_stem}_page{start_page}_{testimony_count}.txt"
                    save_path = os.path.join(pdf_output_folder, filename)
                    
                    with open(save_path, "w", encoding="utf-8") as f:
                        f.write(full_testimony)
                    
                    print(f" Saved to {pdf_stem}/: {filename}")
                    
                    content_buffer = []
                    is_recording = False
                    testimony_count += 1
                    
                    # check if another one starts on the same page
                    if START_PHRASE in parts[1]:
                        is_recording = True
                        start_page = page_num
                        sub_parts = parts[1].split(START_PHRASE, 1)
                        content_buffer.append(START_PHRASE + sub_parts[1])
                else:
                    content_buffer.append(text)
        
        doc.close()
    print("\n--- All work complete! Check the 'oral_testimonies' folder. ---")

if __name__ == "__main__":
    process_pdfs()