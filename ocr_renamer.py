"""
This script renames the .CR2 images in the current working directory by their label (using Tesseract OCR) and D/V tag (using template matching)

Multiscale template matching taken from https://www.pyimagesearch.com/2015/01/26/multi-scale-template-matching-using-python-opencv/
"""

from PIL import Image
import pytesseract
import os
import sys
import rawpy  # to read raw images
import re
import time
import cv2 as cv # pip install opencv-python
import numpy as np
from multiprocessing import Lock, Pool, Manager, Value
from functools import partial

# make all my prints flush immediately because git bash...
print = partial(print, flush=True)

FileExtension = ".CR2"  # File extension of the raw image (if it's not a raw image go change the code in process_image)
threshold = 0.8  # threshold for template match to be accepted

# load templates
template_D = cv.imread('Templates/D.png', 0)  # flag 0 for grayscale image
if template_D is None:
	raise FileNotFoundError("Templates/D.png could not be found")
template_D_width = template_D.shape[1]
template_V = cv.imread('Templates/V.png', 0)
if template_V is None:
	raise FileNotFoundError("Templates/V.png could not be found")


def filter_text(imgtext):
    """
    This function takes in the block of text from Tesseract and tries to find the correct string.
    Returns the string if found, else returns None 
    """
    # Search pattern is of the form: <3 capital alphabets>_<3 capital alphabets><8 digits>      e.g. ZRC_ENT00009431
    # accept false O's in the last part too, and change it later to 0's
    search_pattern = r"\b[A-Z]{3}_[A-Z]{3}([0-9O]){8}\b"
    match = re.search(search_pattern, imgtext)
    if match:
        text = match.group(0)
        if 'O' in text[7:15]:  # replace any O's with 0's
            text = text[0:7] + text[7:15].replace('O', '0')
        return text
    else:
        return None


def rename_img(filename, text, dorsal_ventral):
    """" This function renames the image to its label + D/V/A + <number if filename is taken> """
    global FileExtension
    global renamed_file_counter
    renamed_file_counter.value += 1
    lock.acquire()
    # check if new file name already exists
    new_name = f"{text} {dorsal_ventral}{FileExtension}"
    if not new_name in os.listdir(os.getcwd()):
        os.rename(filename, new_name)
    else:
        n = 1
        new_name = f"{text} {dorsal_ventral}({n}){FileExtension}"
        while new_name in os.listdir(os.getcwd()):
            n += 1
            new_name = f"{text} {dorsal_ventral}({n}){FileExtension}"
        os.rename(filename, new_name)
    print(f"Renaming {filename} to {new_name}")
    lock.release()
    return


def resize_img(img, new_width):
    """ Resize an OpenCV image to a new width, maintaining Aspect Ratio """
    factor = (new_width / float(img.shape[1]))
    new_height = int(img.shape[0] * factor)
    return cv.resize(img, (new_width, new_height), interpolation=cv.INTER_AREA)


def match_template(img):
    """ This function tries to match the D or V template images with the img input, 
    and returns the corresponding letter if the threshold is met
    """

    # resize images near the template size and hope to find a template match (assuming both templates have same width)
    for factor in np.arange(1.2, 2, 0.1):
        gray_img = resize_img(cv.cvtColor(img, cv.COLOR_RGB2GRAY), int(template_D_width * factor))
        try:
            res_D = cv.matchTemplate(gray_img, template_D, cv.TM_CCOEFF_NORMED)
            res_V = cv.matchTemplate(gray_img, template_V, cv.TM_CCOEFF_NORMED)
            val_D = np.amax(res_D)
            val_V = np.amax(res_V)
            if val_D > val_V and val_D > threshold:
                return 'D'
            elif val_V > threshold:
                return 'V'
        except: # todo: is there a better solution to prevent errors where template is smaller than image?
            pass
    return None


def get_largest_labels(rgb_image):
    """ This function gets the largest 3 white labels in the image and returns it
    """
    # apply a threshold to only keep the whites
    img_gray = cv.cvtColor(rgb_image, cv.COLOR_RGB2GRAY)
    _, thresh = cv.threshold(img_gray, 220, 255, cv.THRESH_BINARY)

    # performing opening and closing to remove unwanted noise - see https://docs.opencv.org/trunk/d9/d61/tutorial_py_morphological_ops.html
    kernel = np.ones((10, 10))
    closing = cv.morphologyEx(thresh, cv.MORPH_OPEN, kernel)
    kernel = np.ones((50, 50))
    opening = cv.morphologyEx(closing, cv.MORPH_CLOSE, kernel)

    # grab the largest 3 contours and return their images
    contours, _ = cv.findContours(opening, cv.RETR_TREE, cv.CHAIN_APPROX_SIMPLE)
    segmented_imgs = []
    bgr_image = cv.cvtColor(rgb_image, cv.COLOR_RGB2BGR)
    for contour in sorted(contours, key=cv.contourArea, reverse=True):
        left = min(contour[:, 0, 0])
        right = max(contour[:, 0, 0])
        top = min(contour[:, 0, 1])
        bot = max(contour[:, 0, 1])

        segmented_imgs.append(bgr_image[top:bot, left:right])

    return segmented_imgs

def sort_images(images):
    """ Sorts the images in-place so that the first image in the returned list is the D/V label
    The D/V label is assumed to be the image found that is relatively square-ish """
    for index, image in enumerate(images):
        hw_ratio = image.shape[0] / image.shape[1]
        if hw_ratio > 0.5 and hw_ratio < 2:
            if index != 0:
                images[0], images[index] = images[index], images[0]
                return images

def stack_images(image1, image2):
    """stacks the two images vertically"""
    h1, w1 = image1.shape[:2]
    h2, w2 = image2.shape[:2]
    vis = np.zeros((max(h1, h2), w1+w2, 3), np.uint8)
    vis[:h1, :w1, :3] = image1
    vis[:h2, w1:w1+w2, :3] = image2
    return vis
   


def process_image(filename):
    """This function looks at the raw image from filename and renames it"""
    try:
        # Get openCV image from the raw image
        with rawpy.imread(filename) as raw_image:
            rgb = raw_image.postprocess()  # returns a numpy array

        label_images = get_largest_labels(rgb)

        label_images = sort_images(label_images)
        # do template matching on the 'squarest' image
        template_found = match_template(label_images[0])

        # stack the remaining 2 images into 1
        img = stack_images(label_images[1], label_images[2])
        # initialise some variables for finding the label TWICE before accepting it
        label_found = None  # to hold the finalised label
        labels_found = []  # stores the labels found so far
        starting_width = 300
        ending_width = 4000

        for width in range(starting_width, ending_width + 1, 100):
            img_resized = resize_img(img, width)

            if not label_found:
                # PyTesseract only seems to accept PIL image formats...
                img_text = pytesseract.image_to_string(Image.fromarray(
                    img_resized), config='--psm 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789') 
                text = filter_text(img_text)
                if text:
                    # print(f"{text} label found for {filename} at width {width}")
                    if text in labels_found:
                        label_found = text
                        break
                    else:
                        labels_found.append(text)

        if not label_found and len(labels_found) == 1:  # accept the label even if only found once
            label_found = labels_found[0]

        if label_found:
            if template_found:
                rename_img(filename, label_found, template_found)
            else:
                rename_img(filename, label_found, 'A')

        else:
            unrenamed_files.append(filename)
            # print(f"Unable to find the text for file: {filename}")

    except KeyboardInterrupt:
        pass


# initialise the global variables into the processor pool
def init(l, _unrenamed_files, _renamed_file_counter):
    global lock
    global unrenamed_files
    global renamed_file_counter
    lock = l
    unrenamed_files = _unrenamed_files
    renamed_file_counter = _renamed_file_counter


if __name__ == '__main__':
    start = time.time()
    print("Looking at images...")
    l = Lock()
    manager = Manager()
    _unrenamed_files = manager.list()  # holds shared list of unrenamed files during first round of processing
    _renamed_file_counter = Value('i', 0)
    directory = os.getcwd()
    files = [filename for filename in sorted(os.listdir(directory)) if (filename.endswith(FileExtension) and not filename.startswith('ZRC_ENT'))]
    no_of_files = len(files)

    pool = Pool(initializer=init, initargs=(l, _unrenamed_files, _renamed_file_counter))
    try:
        pool.map_async(process_image, files).get(99999)
    except KeyboardInterrupt:
        pool.terminate()
        pool.join()
        print("Shutting down program...")
        sys.exit(1)
    pool.close()
    pool.join()

    print(f"The script took {(time.time() - start):.1f}s to rename {_renamed_file_counter.value} out of {no_of_files} files.")
    if _unrenamed_files:
        print(f"The files that could not be renamed are:")
        print(_unrenamed_files)
