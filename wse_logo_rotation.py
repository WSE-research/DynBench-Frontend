"""
Functions to control WSE logo rotation in the Streamlit app.
"""

from streamlit.components.v1 import html


def start_wse_logo_rotation():
    """
    Start rotating the WSE logo in the header.
    """
    html(
        """
        <script>
        var logo = parent.window.document.querySelector("#WSElogo");
        if (logo) {
            logo.classList.add('rotating');
        }
        </script>
        """,
        height=0
    )


def stop_wse_logo_rotation():
    """
    Stop rotating the WSE logo and reset it to normal state.
    """
    html(
        """
        <script>
        var logo = parent.window.document.querySelector("#WSElogo");
        if (logo) {
            logo.classList.remove('rotating');
            void logo.offsetWidth; // trigger browser reflow
        }
        </script>
        """,
        height=0
    )
