package vn.unit.affordability.dossier.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.unit.affordability.dossier.model.Dossier;

import java.util.List;

@Repository
public interface DossierRepository extends JpaRepository<Dossier, String> {

    boolean existsByApplicationId(String applicationId);

    List<Dossier> findByApplicantId(String applicantId);

    List<Dossier> findByStatus(String status);
}
