// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <sstream>
#include <string>

#include <QTemporaryDir>
#include <QUrl>

#include "InitApplication.h"
#include <App/ProjectFile.h>
#include <App/InventorObject.h>
#include <Base/FileInfo.h>
#include <Base/Stream.h>
#include <Base/Type.h>
#include <Base/Writer.h>

namespace
{
bool writeProjectArchive(const QString& path, const std::string& documentXml)
{
    Base::ofstream archive(
        Base::FileInfo(path.toStdString()),
        std::ios::out | std::ios::binary | std::ios::trunc
    );
    if (!archive.is_open()) {
        return false;
    }

    {
        Base::ZipWriter writer(archive);
        writer.putNextEntry("Document.xml");
        writer.Stream() << documentXml;
        if (!writer.Stream().good()) {
            return false;
        }
    }

    archive.flush();
    if (!archive.good()) {
        return false;
    }
    archive.close();
    return !archive.fail();
}
}  // namespace

// NOLINTBEGIN
class ProjectFileTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }
    void SetUp() override
    {}
    void TearDown() override
    {}
    std::string fileName() const
    {
        std::string resDir(DATADIR);
        resDir.append("/tests/ProjectTest.FCStd");
        return resDir;
    }
    std::string imageFileName() const
    {
        return {"thumbnails/Thumbnail.png"};
    }
    std::list<std::string> getInventorObjects() const
    {
        return {"Body"};
    }
    Base::Type getInventorId() const
    {
        return App::InventorObject::getClassTypeId();
    }
};

TEST_F(ProjectFileTest, loadInvalid)
{
    App::ProjectFile proj("non-existing.FCStd");
    EXPECT_FALSE(proj.loadDocument());
}

TEST_F(ProjectFileTest, loadDocument)
{
    App::ProjectFile proj(fileName());
    EXPECT_TRUE(proj.loadDocument());
}

TEST_F(ProjectFileTest, externalDtdIsRejected)
{
    constexpr auto sentinel = "OPENFUSION_EXTERNAL_DTD_SENTINEL";
    constexpr auto controlValue = "OPENFUSION_PROJECTFILE_CONTROL";
    QTemporaryDir temporaryDirectory;
    ASSERT_TRUE(temporaryDirectory.isValid());

    const QString controlArchive = temporaryDirectory.filePath("control.FCStd");
    std::ostringstream controlXml;
    controlXml << "<?xml version='1.0' encoding='utf-8'?>\n"
               << "<Document ProgramVersion=\"Test\">\n"
               << "  <Properties Count=\"1\">\n"
               << "    <Property name=\"Comment\" type=\"App::PropertyString\">\n"
               << "      <String value=\"" << controlValue << "\"/>\n"
               << "    </Property>\n"
               << "  </Properties>\n"
               << "  <Objects Count=\"0\"/>\n"
               << "  <ObjectData Count=\"0\"/>\n"
               << "</Document>\n";
    ASSERT_TRUE(writeProjectArchive(controlArchive, controlXml.str()));

    App::ProjectFile controlProject(controlArchive.toStdString());
    ASSERT_TRUE(controlProject.loadDocument());
    EXPECT_EQ(controlProject.getMetadata().comment, controlValue);

    const QString externalDtd = temporaryDirectory.filePath("external.dtd");
    const QString projectArchive = temporaryDirectory.filePath("external-dtd.FCStd");

    {
        Base::ofstream dtd(
            Base::FileInfo(externalDtd.toStdString()),
            std::ios::out | std::ios::binary | std::ios::trunc
        );
        ASSERT_TRUE(dtd.is_open());
        dtd << "<!ELEMENT Document (Properties, Objects, ObjectData)>\n"
            << "<!ATTLIST Document ProgramVersion CDATA #IMPLIED>\n"
            << "<!ELEMENT Properties (Property*)>\n"
            << "<!ATTLIST Properties Count CDATA #IMPLIED>\n"
            << "<!ELEMENT Property (String)>\n"
            << "<!ATTLIST Property name CDATA #REQUIRED type CDATA #IMPLIED>\n"
            << "<!ELEMENT String EMPTY>\n"
            << "<!ATTLIST String value CDATA #IMPLIED>\n"
            << "<!ELEMENT Objects EMPTY>\n"
            << "<!ATTLIST Objects Count CDATA #IMPLIED>\n"
            << "<!ELEMENT ObjectData EMPTY>\n"
            << "<!ATTLIST ObjectData Count CDATA #IMPLIED>\n"
            << "<!ENTITY externalMetadata \"" << sentinel << "\">\n";
        dtd.flush();
        ASSERT_TRUE(dtd.good());
        dtd.close();
        ASSERT_FALSE(dtd.fail());
    }

    const QUrl externalDtdUrl = QUrl::fromLocalFile(externalDtd);
    ASSERT_TRUE(externalDtdUrl.isValid());
    ASSERT_TRUE(externalDtdUrl.isLocalFile());
    ASSERT_EQ(externalDtdUrl.toLocalFile(), externalDtd);

    std::ostringstream externalDtdXml;
    externalDtdXml << "<?xml version='1.0' encoding='utf-8'?>\n"
                   << "<!DOCTYPE Document SYSTEM \""
                   << externalDtdUrl.toEncoded().toStdString() << "\">\n"
                   << "<Document ProgramVersion=\"Test\">\n"
                   << "  <Properties Count=\"1\">\n"
                   << "    <Property name=\"Comment\" type=\"App::PropertyString\">\n"
                   << "      <String value=\"&externalMetadata;\"/>\n"
                   << "    </Property>\n"
                   << "  </Properties>\n"
                   << "  <Objects Count=\"0\"/>\n"
                   << "  <ObjectData Count=\"0\"/>\n"
                   << "</Document>\n";
    ASSERT_TRUE(writeProjectArchive(projectArchive, externalDtdXml.str()));

    App::ProjectFile project(projectArchive.toStdString());
    EXPECT_FALSE(project.loadDocument());
}

TEST_F(ProjectFileTest, getObjects)
{
    App::ProjectFile proj(fileName());
    EXPECT_TRUE(proj.loadDocument());
    std::list<App::ProjectFile::Object> objs = proj.getObjects();
    EXPECT_EQ(objs.size(), 1);
}

TEST_F(ProjectFileTest, getPropertyFiles)
{
    App::ProjectFile proj(fileName());
    EXPECT_TRUE(proj.loadDocument());
    std::list<App::ProjectFile::PropertyFile> files = proj.getPropertyFiles("Body");
    EXPECT_EQ(files.size(), 0);
}

TEST_F(ProjectFileTest, getMetadata)
{
    App::ProjectFile proj(fileName());
    EXPECT_TRUE(proj.loadDocument());
    auto metadata = proj.getMetadata();
    EXPECT_EQ(std::string("No comment"), metadata.comment);
    EXPECT_EQ(std::string("John Doe & Jane Roe"), metadata.company);
    EXPECT_EQ(std::string("John Doe"), metadata.createdBy);
    EXPECT_EQ(std::string("2024-03-08T10:53:31Z"), metadata.creationDate);
    EXPECT_EQ(std::string("ProjectTest"), metadata.label);
    EXPECT_EQ(std::string("John Doe"), metadata.lastModifiedBy);
    EXPECT_EQ(std::string("2024-03-08T11:03:44Z"), metadata.lastModifiedDate);
    EXPECT_EQ(std::string("Public Domain"), metadata.license);
    EXPECT_EQ(std::string("https://en.wikipedia.org/wiki/Public_domain"), metadata.licenseURL);
    EXPECT_EQ(std::string("0.22R36329 (Git)"), metadata.programVersion);
    EXPECT_EQ(std::string("6847155d-dcc3-4dea-92c9-c4d32d6a3055"), metadata.uuid);
}

TEST_F(ProjectFileTest, getObjectsOfType)
{
    App::ProjectFile proj(fileName());
    EXPECT_TRUE(proj.loadDocument());
    std::list<std::string> objs = proj.getObjectsOfType(getInventorId());
    EXPECT_EQ(objs, getInventorObjects());
}

TEST_F(ProjectFileTest, restoreObject)
{
    App::ProjectFile proj(fileName());
    EXPECT_TRUE(proj.loadDocument());
    App::InventorObject obj;
    EXPECT_TRUE(proj.restoreObject("Body", &obj, false));
    EXPECT_EQ(obj.Label.getStrValue(), std::string("Body"));
}

TEST_F(ProjectFileTest, getTypeId)
{
    App::ProjectFile proj(fileName());
    EXPECT_TRUE(proj.loadDocument());
    Base::Type id = proj.getTypeId("Body");
    EXPECT_EQ(id, getInventorId());
}

TEST_F(ProjectFileTest, getThumbnailBuffer)
{
    App::ProjectFile proj(fileName());
    std::stringstream str;
    proj.readInputFileDirect(imageFileName(), str);
    std::string buffer = str.str();
    EXPECT_EQ(buffer.size(), 2857);
}

TEST_F(ProjectFileTest, getThumbnailFile)
{
    App::ProjectFile proj(fileName());
    Base::FileInfo fi(Base::FileInfo::getTempFileName());
    Base::ofstream file(fi, std::ios::out | std::ios::binary);
    proj.readInputFileDirect(imageFileName(), file);
    file.flush();
    file.close();
    EXPECT_EQ(fi.size(), 2857);
    fi.deleteFile();
}
// NOLINTEND
