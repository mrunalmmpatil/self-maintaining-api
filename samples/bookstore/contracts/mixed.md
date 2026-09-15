GET /books/{book_id} moves to /catalog/books/{book_id}; behavior and response are otherwise unchanged.
country is now required. The current application has no customer country input or source. Document the application boundary and caller changes needed; do not invent or hardcode a country.
