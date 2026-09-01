/******************************************************************************
  This file is part of the FreeCAD CAx development system.

  Copyright (c) 2014-2023 3Dconnexion.

  This source code is released under the GNU Library General Public License, (see "LICENSE").
******************************************************************************/

extern "C" {
  extern long NlLoadLibrary();

  long NlEnsureLoaded() {
    // Function-local static initialization is thread-safe since C++11. Keep
    // optional driver discovery out of process image initialization so
    // headless metadata commands do not touch platform GUI integrations.
    static const long error = NlLoadLibrary();
    return error;
  }
}
