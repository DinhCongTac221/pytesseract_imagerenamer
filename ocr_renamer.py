from PIL import Image
import pytesseract
import os
import rawpy # to read raw images
import re
import time
import cv2 #pip install opencv-python
import numpy as np
from multiprocessing import Lock, Pool, Manager, Value

### Modify the variables here ###
FileExtension = ".CR2" # File extension of the image
threshold = 0.9 # threshold for template match to be accepted

# setup templates
template_D = cv2.imread('Templates/D.png', 0) # flag 0 for grayscale image
if template_D is None:
	raise FileNotFoundError("Templates/D.png could not be found")
template_V = cv2.imread('Templates/V.png', 0)
if template_V is None:
	raise FileNotFoundError("Templates/V.png could not be found")


def filter_text(imgtext):
    """"
    This function takes in the block of text from Tesseract and tries to find the correct string.
    Returns the string if found, else returns None 
    """
    # Search pattern is of the form: <3 capital alphabets>_<3 capital alphabets><8 digits>      e.g. ZRC_ENT00009431
    search_pattern = r"\b[A-Z]{3}_[A-Z]{3}([0-9O]){8}\b"  # accept false O's in the last bit too, and change it later to 0's 
    # search_pattern = r"[A-Z]{3}_[A-Z]{3}([0-9O]){4}([1-9])([0-9O]){3}\b" # modified search pattern to reject 0's in the 5th number
    match = re.search(search_pattern,imgtext)
    if match:
        text = match.group(0) # get the string from the match object - what if there are multiple matches? hmm
        if 'O' in text[7:15]: #replace any O's with 0's
            text = text[0:7] + text[7:15].replace('O','0')
        return text
    else:
        return None


def rename_img(filename, text, dorsal_ventral):
    global FileExtension
    global renamed_file_counter
    renamed_file_counter.value += 1
    """" This function renames the image to its label + D/V/A + <number if filename is taken> """
    if not (f"{text} {dorsal_ventral}{FileExtension}") in os.listdir(os.getcwd()): #check if new file name already exists
        os.rename(filename, f"{text} {dorsal_ventral}{FileExtension}")
        print(f"Renaming {filename} to {text} {dorsal_ventral}{FileExtension}", flush=True)
    else:
        n = 1
        while (f"{text} {dorsal_ventral}({n}){FileExtension}") in os.listdir(os.getcwd()):
            n += 1
        os.rename(filename, f"{text} {dorsal_ventral}({n}){FileExtension}")
        print(f"Renaming {filename} to {text} {dorsal_ventral}({n}){FileExtension}", flush=True)
    return

def resize_img(img, new_width):
    """ Resize an OpenCV image to a new width, maintaining Aspect Ratio """
    factor = (new_width / float(img.shape[1]))
    new_height = int(img.shape[0] * factor)
    return cv2.resize(img, (new_width, new_height), interpolation = cv2.INTER_AREA)

def match_template(img):
    """ This function tries to match the D or V template images with the img input, 
    and returns either a 'D' or 'V' if either match, else returns 'A'
    """
    flag_D = False
    flag_V = False
    ret = ""
    global template_D
    global template_V
    res_D = cv2.matchTemplate(img, template_D, cv2.TM_CCOEFF_NORMED)
    res_V = cv2.matchTemplate(img, template_V, cv2.TM_CCOEFF_NORMED)
    if np.amax(res_D) > threshold:
        flag_D = True
    if np.amax(res_V) > threshold:
        flag_V = True

    if flag_D == True and flag_V == True:
        print("Both D and V detected!")
        ret = "A"
    elif flag_D == True:
        ret = "D"
    elif flag_V == True:
        ret = "V"
    else:
        # print("Neither D nor V was detected!")
        ret = "A"
    
    return ret

def process_image(filename):
    # print(f"Looking at file: {filename}", flush=True)
    with rawpy.imread(filename) as raw_image: #with so that the file is closed after reading
        rgb = raw_image.postprocess() # return a numpy array
    img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR) # convert into openCV image
    text_found = 0
    for width in range(600,2201,100): # Try a few different image sizes until OCR detects a long enough string
        img_resized = resize_img(img, width)
        # PyTesseract only seems to accept PIL image formats
        imgtext=pytesseract.image_to_string(Image.fromarray(img_resized), config='--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789') #Get data output and split into list
        text = filter_text(imgtext)
        if text: 
            text_found = 1
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) # convert to grayscale for template matching
            result = match_template(gray) # use openCV template to find if D or V template detected
            lock.acquire()
            rename_img(filename, text, result)
            lock.release()
            break
    if text_found == 0:
        round_one_unrenamed_files.append(filename)
        # print(f"Unable to find the text for file: {filename}", flush=True)

def process_image_finer(filename):
    # print(f"Looking at file: {filename}", flush=True)
    with rawpy.imread(filename) as raw_image: 
        rgb = raw_image.postprocess() # return a numpy array
    img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR) # convert into openCV image
    text_found = 0
    for width in range(600,3051,50): # Try more and see if we get lucky?
        if width % 100 != 0 or width > 2101: #only perform for sizes not already tried
            img_resized = resize_img(img, width)
            imgtext=pytesseract.image_to_string(Image.fromarray(img_resized), config='--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789') #Get data output and split into list
            text = filter_text(imgtext)
            if text: 
                text_found = 1
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) # convert to grayscale for template matching
                result = match_template(gray) # use openCV template to find if D or V template detected
                lock.acquire()
                rename_img(filename, text, result)
                lock.release()
                break
                
        # ## Using a different config on pytesseract seems to cause no output suddenly?? (or was this already the case?) Find out why
        # imgtext=pytesseract.image_to_string(img) #Get data output and split into list
        # text = filter_text(imgtext)
        # if text: 
        #     rename_img(text)
        #     text_found = 1
        #     break
    if text_found == 0:
        failed_files.append(filename)
        # print(f"Still unable to find the text for file: {filename}", flush=True)

def init(l, _round_one_unrenamed_files, _failed_files, _renamed_file_counter): # initialise the global variables into the processor pool
    global lock
    global round_one_unrenamed_files
    global renamed_file_counter
    global failed_files
    lock = l
    round_one_unrenamed_files = _round_one_unrenamed_files
    renamed_file_counter = _renamed_file_counter
    failed_files = _failed_files

if __name__ == '__main__':
    start = time.time()
    print("Looking at images...", flush=True)
    l = Lock()
    manager = Manager()
    _round_one_unrenamed_files = manager.list() # holds shared list of unrenamed files during first round of processing
    _failed_files = manager.list() # holds shared list of files that could not be renamed after all processing
    _renamed_file_counter = Value('i', 0)
    directory = os.getcwd()
    files = [filename for filename in sorted(os.listdir(directory)) if filename.endswith(FileExtension) and not filename.startswith('ZRC_ENT')]
    no_of_files = len(files)

    pool = Pool(initializer=init, initargs=(l, _round_one_unrenamed_files, _failed_files, _renamed_file_counter))
    pool.map(process_image, files)

    if _round_one_unrenamed_files:
        print("Trying further steps on files that could not be renamed...", flush=True)
        # print(_round_one_unrenamed_files, flush=True)
        pool.map(process_image_finer, _round_one_unrenamed_files)

    pool.close()
    pool.join()

    print(f"The script took {(time.time() - start):.1f}s to rename {_renamed_file_counter.value} out of {no_of_files} files.")
    if _failed_files:
        print(f"The files that could not be renamed are:")
        print(_failed_files)