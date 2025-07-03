# LSP for XML, built in Python

Wednesday,  2 July 2025, 20:58

I looked but could not find an LSP for XML that would suit my needs.

There is something managed out of the Eclipse project,
[Lemminx](https://github.com/eclipse-lemminx/lemminx), which I guess Redhat
manages. But it does not support XSD 1.1 and it's sort of brittle and
non-extensible. When I tried adding XSD 1.1 capability, it broke and threw some
of the most obscure stacktraces I've ever seen. I didn't have the appetite to
go sort that out.

I didn't find any others.

One night, pretty late, I thought _it can't be that hard_, and I started writing
an LSP, with Gemini's help, in python, based on the xmlschema module and
pygls. And actually, it _wasn't that hard_.

This thing is a homemade wonder.

It's sort of informal and not well tested. It doesn't have a ton of features.
But it works for basic validation and error messages, and it has completion
suggestions too. It works for me for the XML files I need to modify.

It does validation and completion. It sends back diagnostics to let the editor
highlight lines that are problematic.

Tested (tried, really), _only in emacs v30.1_  with nxml-mode and :
 - a bunch of Apigee files
 - MSBuild .csproj
 - maven pom.xml

Actually I think the default capability of nxml to use rnc schema, is still probably 
preferred. But, most XML files that I work with do not have rnc schema, and the 
"just convert your XSD to rnc" is not a rabbit hole I want to descend into. 

So I would say, if you can use nxml with rnc, do it.  If you have only XSD, then 
maybe this will work. 



## Running the server

It depends on puython 3.12 or later,

To use it:

1. unpack

2. create a venv
   ```sh
   python -m venv .venv
   ```

3. activate
   ```sh
   source .venv/bin/activate
   ```

You're ready,

You can start it with
```sh
python xmllsp/xml_language_server/xmllsp.py
```
... but that won't do much good. Normally your editor will start the server .
The server uses stdio for interaction.


## Using it

The initialization message should look like this:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "processId": 2482025,
    "clientInfo": { "name": "Eglot", "version": "1.18" },
    "rootPath": "/path/to/directory/containing/xmlfile",
    "rootUri": "file:///path/to/directory/containing/xmlfile",
    "initializationOptions": {
      "schemaLocators": [
        {
          "rootElement": true,
          "searchPaths": [
            "/path/to/directory/containing/schema-inference/dist/schema"
          ]
        },
        {
          "locationHint": "/path/to/xml-schema-cache/schema_map.json"
        },
        {
          "patterns": [
            {
              "pattern": "*.csproj",
              "path": "/path/to/Microsoft.Build.Core.xsd",
              "useDefaultNamespace": true
            }
          ]
        }
      ]
    }
    ....
  }
}
```


The interesting thing in the `initializationOptions` is the `schemaLocators` . There are three options:

- `rootElement` - it examines the root element of the doc being edited, and looks in the
  searchPaths directories for a file like ELEMENTNAME.xsd, and uses that as the schema, if found.
  First file it finds, wins.

- `locationHint` - some XML files have a `xsi:schemaLocation` attribute at the top level.
  That location is sometimes a resolvable URI and sometimes not. Anyway the server does not
  retrieve XSD from remote locations. Instead it looks in the json file specified by
  `locationHint` , for a map of these "schemaLocation" values to a path ... in the same
  directory as the json file, of XSD files. Example
  ```json
  {
    "http://maven.apache.org/xsd/maven-4.0.0.xsd": "maven-4.0.0.xsd"
  }
  ```

  To get this to work, you need to have downloaded the maven XSD and placed it
  in the same directory next to the JSON map file.

- `patterns` - This maps from filename glob patterns to specific schema.
  There is an optional `useDefaultNamespace` which tells the server that, for files that
  match this pattern, infer a default namespace taken from the XSD file,
  even if the XML file being edited doesn't specify a namespace. The Microsoft build
  project files do this - they have a schema that they supposedly conform to, but the
  schema is namespace-qualified, though their XML files are not. (shrug)

The order in which you specify these locators is the order in which they will be tried.
You should not include more than one of { `rootElement`, `locationHint`, `patterns` } in
any of those `schemaLocators` items.

You do not need to specify more than one item in `schemaLocators`. What I found was that
one locator approach was insufficient to cover all cases. So multiple options gives some
flexibility.

## Editor specific configuration

I used language like "you need to specify ..." above, describing what the
initialization message must be.  But you generally don't have direct control
over that initialization message. It is something your LSP client generates and
sends to the LSP Server .  How you get your LSP client to send that data, is
sort of dependent upon the LSP client / editor.

Using emacs and eglot, you can use something like this for initialization of the server:

```elisp
(defun my-xmllsp-init-options (_server)
  "options for the cut-rate XML LSP, built in python."
  (let* ((home-dir  (getenv "HOME") )
         (xsd-cachedir (concat home-dir "/xml-schema-cache")))
    `(:schema_locators
      [
       (:rootelement t
        :searchpaths
         [
          ,(concat home-dir "/my-schema-dir")
         ])
       (:location_hint ,(concat xsd-cachedir "/schema_map.json"))
       (:patterns [(:pattern "*.csproj"
                    :path ,(concat xsd-cachedir "/Microsoft.Build.Core.xsd")
                    :use_default_namespace t
                   )])
      ]
     )))


(with-eval-after-load 'eglot
  (add-to-list
   'eglot-server-programs
   `(nxml-mode .
               (,(concat (getenv "HOME") "/xmllsp/.venv/bin/python"
                ,(concat (getenv "HOME") "/xmllsp/xml_language_server/xmllsp.py")
                :initializationOptions my-xmllsp-init-options))))
```

The above tells eglot how to start the server, and how to get the initialization options.
This assumes you have extracted the xmllsp into ~/xmllsp , and you created a python venv, and so on.

## Messages this LSP implements

- **initialize**
- **workspace/didChangeConfiguration** - no-op
- **textDocument/didOpen**
- **textDocument/didChange**
- **textDocument/didSave**
- **textDocument/didClose**
- **textDocument/completion**

The LSP does send back publishDiagnostic messages for validation errors.


## License

This material is [Copyright © 2025 Google LLC](./NOTICE).
and is licensed under the [Apache 2.0 License](LICENSE). This includes the Java
code as well as the API Proxy configuration.


## Disclaimer

This example is not an official Google product, nor is it part of an
official Google product.

