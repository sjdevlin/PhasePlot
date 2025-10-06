import customtkinter 
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from services import Movie2Tiff

class ImageRunDetailView():
    def __init__(self):

        self.convertor = Movie2Tiff()  # Initialize the converter service

        self.root_window = customtkinter.CTkToplevel()  # Bare class is passed TK root_window widget.
        self.root_window.title("Result Viewer")
        self.root_window.geometry("1000x600")

        # Main container frame that fills the root_window window.
        self.home_frame = customtkinter.CTkFrame(self.root_window)
        self.home_frame.pack(fill="both", expand=True)
        
        # Configure a 3-row grid in the home frame.
        self.home_frame.grid_rowconfigure(0, weight=0)  # Intro row (fixed height)
        self.home_frame.grid_rowconfigure(1, weight=1)  # Table row (expandable)
        self.home_frame.grid_rowconfigure(2, weight=0)  # Button row (fixed height)
        
        # ----------------------------
        # Top Row: Intro Frame
        # ----------------------------
        
        self.description_label = customtkinter.CTkLabel(
            self.home_frame,
            text_color='white',
            text=(
                'Meta Data Here'
            )
        )
        # Using grid inside the intro_frame.
        self.description_label.grid(row=0, column=0, sticky="", padx=10, pady=10)

        # ----------------------------
        # Second Row: Photo
        # ----------------------------
        self.photo_frame = customtkinter.CTkFrame(
            self.home_frame,
            width=700,
            height=500,
            fg_color='transparent'
        )

        self.photo_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10) 
        # Image display label (acts as a placeholder for the TIFF image)
        self.image_label = customtkinter.CTkLabel(
            self.photo_frame,
            width=600,
            height=400,
            text="",  # No text, just for image
            fg_color="#222222"  # Optional: background color for visibility
        )
        self.image_label.pack(expand=True)


        self.prev_stack_button = customtkinter.CTkButton(
            master=self.home_frame,
            text="Down in Stack",
            state=customtkinter.NORMAL
        )
        self.prev_stack_button.grid(sticky="n",row=1, column=1, padx=5, pady=80)

        self.next_stack_button = customtkinter.CTkButton(
            master=self.home_frame,
            text="Up in Stack",
            state=customtkinter.NORMAL
        )
        self.next_stack_button.grid(sticky="s",row=1, column=1, padx=5, pady=80)


        # ----------------------------
        # Bottom Row: Button Frame
        # ----------------------------
        self.button_frame = customtkinter.CTkFrame(
            self.home_frame,
            width=600,
            height=30,
            fg_color='transparent'
        )
        self.button_frame.grid(row=2, column=0, sticky="ew")
        
        # Configure a 3-column grid in the button frame.
        for col in range(3):
            self.button_frame.grid_columnconfigure(col, weight=1)
                
        self.prev_sample_button = customtkinter.CTkButton(
            master=self.button_frame,
            text="Prev Sample",
            state=customtkinter.NORMAL
        )
        self.prev_sample_button.grid(sticky="",row=0, column=0, padx=5, pady=10)

        self.next_sample_button = customtkinter.CTkButton(
            master=self.button_frame,
            text="Next Sample",
            state=customtkinter.NORMAL
        )
        self.next_sample_button.grid(sticky="",row=0, column=1, padx=5, pady=10)

        self.prev_site_button = customtkinter.CTkButton(
            master=self.button_frame,
            text="Prev Site",
            state=customtkinter.NORMAL
        )
        self.prev_site_button.grid(sticky="",row=0, column=2, padx=5, pady=10)
        self.next_site_button = customtkinter.CTkButton(
            master=self.button_frame,
            text="Next Site",
            state=customtkinter.NORMAL
        )
        self.next_site_button.grid(sticky="",row=0, column=3, padx=5, pady=10)

    def show_image(self, path_to_tiff, meta_data=None):
        """
        Load the TIFF from disk, resize it to fit the placeholder,
        and display it in image_label.
        """
        try:
            print(f"Attempting to load image: {path_to_tiff}")
            
            # Update metadata display if provided
            if meta_data:
                self.description_label.configure(text=meta_data)
            
            # 1) Open the image
            img = Image.open(path_to_tiff)
            print(f"Original image mode: {img.mode}, size: {img.size}")
            
            # Handle different image formats
            if img.mode == 'I;16':
                # Convert 16-bit to 8-bit by normalizing (for backward compatibility)
                import numpy as np
                img_array = np.array(img)
                print(f"Processing 16-bit image: shape {img_array.shape}, dtype: {img_array.dtype}")
                print(f"Min value: {img_array.min()}, Max value: {img_array.max()}")
                
                # Check if the image has any meaningful data
                if img_array.max() == img_array.min():
                    print("Warning: Image appears to have uniform values")
                    img_array = np.full_like(img_array, 128, dtype=np.uint8)
                else:
                    # Use percentile-based normalization for better contrast
                    p2, p98 = np.percentile(img_array, (2, 98))
                    print(f"2nd percentile: {p2}, 98th percentile: {p98}")
                    
                    # Clip values to remove extreme outliers
                    img_array = np.clip(img_array, p2, p98)
                    
                    # Normalize to 0-255 range
                    img_array = ((img_array - p2) * 255 / (p98 - p2)).astype(np.uint8)
                
                img = Image.fromarray(img_array, mode='L')  # Convert to 8-bit grayscale
                print(f"Converted 16-bit to 8-bit grayscale, new min/max: {img_array.min()}/{img_array.max()}")
            
            elif img.mode == 'L':
                # 8-bit grayscale - no conversion needed
                print("Processing 8-bit grayscale image")
                
            elif img.mode == 'P':
                # Palette mode - convert to grayscale
                print("Converting palette image to grayscale")
                img = img.convert('L')
                
            # Convert to RGB for display
            if img.mode != 'RGB':
                img = img.convert('RGB')
                print(f"Converted to RGB mode")
            
            # 2) Calculate new size while maintaining aspect ratio
            target_width, target_height = 600, 400
            img_width, img_height = img.size
            
            # Calculate scaling factor
            scale = min(target_width / img_width, target_height / img_height)
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)
            
            print(f"Scaling factor: {scale}, new size: {new_width}x{new_height}")
            
            # Resize the image
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 3) Convert to a CTkImage with both light and dark versions
            ctk_img = customtkinter.CTkImage(
                light_image=img, 
                dark_image=img,  # Use same image for both themes
                size=(new_width, new_height)
            )

            # 4) Update the label
            self.image_label.configure(image=ctk_img, text="")
            self.description_label.configure(text=meta_data if meta_data else "No metadata available")
            
            # 5) Keep a reference around so Tkinter doesn't GC it
            self.image_label.image = ctk_img
            print("Image successfully loaded and displayed")
            
        except Exception as e:
            print(f"Error loading image {path_to_tiff}: {e}")
            import traceback
            traceback.print_exc()
            # Show error message in label
            self.image_label.configure(image=None, text=f"Error loading image:\n{str(e)}")

