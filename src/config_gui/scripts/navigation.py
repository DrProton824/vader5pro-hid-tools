from __future__ import annotations

from ctkmaker import CTkScript


class NavigationController(CTkScript):

    def get_root(self):
        root = self.widget
        while root.master is not None:
            root = root.master
        return root

    def hide_pages(self):
        root = self.get_root()

        root.frame_mapping.pack_forget()
        root.frame_macros.pack_forget()
        root.frame_profiles.pack_forget()
        root.frame_settings.pack_forget()
        root.frame_about.pack_forget()

    def show_page(self, page):
        self.hide_pages()
        page.pack(fill="both", expand=True)

    def mapping(self):
        root = self.get_root()
        self.show_page(root.frame_mapping)

    def macros(self):
        root = self.get_root()
        self.show_page(root.frame_macros)

    def profiles(self):
        root = self.get_root()
        self.show_page(root.frame_profiles)

    def settings(self):
        root = self.get_root()
        self.show_page(root.frame_settings)

    def about(self):
        root = self.get_root()
        self.show_page(root.frame_about)