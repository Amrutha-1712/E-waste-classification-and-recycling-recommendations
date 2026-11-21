from __future__ import annotations

import streamlit as st
from PIL import Image, UnidentifiedImageError

from backend.component_info import get_component_info
from backend.model_service import ModelUnavailableError, get_classifier


@st.cache_resource
def _load_classifier():
    return get_classifier()


def main() -> None:
    st.set_page_config(page_title="Laptop Component Classifier")
    st.title("Laptop Component Classifier")
    st.write("Upload a component image or take a photo with your camera.")

    source = st.radio("Image source", ("Upload image", "Take a photo"))
    if source == "Upload image":
        image_file = st.file_uploader(
            "Choose a component image", type=("jpg", "jpeg", "png", "webp")
        )
    else:
        image_file = st.camera_input("Capture a component image")

    if image_file is None:
        return

    try:
        with Image.open(image_file) as uploaded_image:
            image = uploaded_image.convert("RGB")
    except (UnidentifiedImageError, OSError):
        st.error("The selected image is invalid or corrupted.")
        return

    st.image(image, caption="Image to classify")
    if not st.button("Classify image", type="primary"):
        return

    try:
        classifier = _load_classifier()
        prediction = classifier.predict(image)
    except ModelUnavailableError as error:
        st.error(str(error))
        return

    st.text(get_component_info(prediction["component"]))


if __name__ == "__main__":
    main()
